import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy import func, select

from .config import settings
from .db import session_factory
from .models import Message, Turn, TurnEvent, now_utc

logger = logging.getLogger(__name__)
running_turns: dict[uuid.UUID, asyncio.Task[None]] = {}


async def append_event(turn_id: uuid.UUID, event_type: str, payload: dict[str, object]) -> None:
    async with session_factory() as session:
        sequence = (
            await session.scalar(
                select(func.coalesce(func.max(TurnEvent.sequence), 0)).where(
                    TurnEvent.turn_id == turn_id
                )
            )
        ) + 1
        session.add(
            TurnEvent(turn_id=turn_id, sequence=sequence, event_type=event_type, payload=payload)
        )
        await session.commit()


async def execute_direct_turn(turn_id: uuid.UUID) -> None:
    assistant_id = uuid.uuid4()
    text = ""
    try:
        async with session_factory() as session:
            turn = await session.get(Turn, turn_id)
            if turn is None:
                return
            turn.state = "running"
            turn.updated_at = now_utc()
            history = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == turn.conversation_id)
                        .order_by(Message.created_at, Message.id)
                    )
                ).all()
            )
            session.add(
                Message(
                    id=assistant_id,
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    role="assistant",
                    content="",
                    status="streaming",
                )
            )
            await session.commit()
            request_body = {
                "model": f"yandex/{settings.llm_model}",
                "input": [
                    {"role": item.role, "content": item.content} for item in history if item.content
                ],
                "max_output_tokens": settings.llm_max_output_tokens,
                "stream": True,
                "metadata": {
                    "conversation_id": str(turn.conversation_id),
                    "turn_id": str(turn.id),
                    "user_id": str(turn.owner_id),
                    "correlation_id": turn.correlation_id,
                },
            }

        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10)
        parent_span_id = uuid.uuid4().hex[:16]
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{settings.bifrost_url}/v1/responses",
                json=request_body,
                headers={
                    "Accept": "text/event-stream",
                    "x-request-id": turn.correlation_id,
                    "traceparent": f"00-{turn.correlation_id}-{parent_span_id}-01",
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if not raw or raw == "[DONE]":
                        continue
                    upstream = json.loads(raw)
                    if upstream.get("type") == "response.output_text.delta":
                        delta = str(upstream.get("delta", ""))
                        text += delta
                        await append_event(turn_id, "assistant.delta", {"delta": delta})

        async with session_factory() as session:
            turn = await session.get(Turn, turn_id)
            message = await session.get(Message, assistant_id)
            if turn and message:
                message.content = text
                message.status = "complete"
                turn.state = "completed"
                turn.updated_at = now_utc()
                await session.commit()
        await append_event(
            turn_id, "turn.completed", {"message_id": str(assistant_id), "content": text}
        )
    except asyncio.CancelledError:
        async with session_factory() as session:
            turn = await session.get(Turn, turn_id)
            message = await session.get(Message, assistant_id)
            if turn:
                turn.state = "cancelled"
                turn.updated_at = now_utc()
            if message:
                message.content = text
                message.status = "incomplete"
            await session.commit()
        await append_event(turn_id, "turn.cancelled", {"content": text})
    except Exception:
        correlation_id = "unknown"
        async with session_factory() as session:
            turn = await session.get(Turn, turn_id)
            message = await session.get(Message, assistant_id)
            if turn:
                correlation_id = turn.correlation_id
                turn.state = "failed"
                turn.error_code = "upstream_unavailable"
                turn.updated_at = now_utc()
            if message:
                message.content = text
                message.status = "incomplete"
            await session.commit()
        logger.exception("Direct turn failed correlation_id=%s turn_id=%s", correlation_id, turn_id)
        await append_event(
            turn_id,
            "turn.failed",
            {
                "code": "upstream_unavailable",
                "message": "The model service could not complete this turn.",
                "correlation_id": correlation_id,
            },
        )
    finally:
        running_turns.pop(turn_id, None)


def start_turn(turn_id: uuid.UUID) -> None:
    running_turns[turn_id] = asyncio.create_task(execute_direct_turn(turn_id))


async def cancel_turn(turn_id: uuid.UUID) -> bool:
    task = running_turns.get(turn_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def event_stream(turn_id: uuid.UUID, after: int) -> AsyncIterator[str]:
    idle_ticks = 0
    while True:
        async with session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(TurnEvent)
                        .where(TurnEvent.turn_id == turn_id, TurnEvent.sequence > after)
                        .order_by(TurnEvent.sequence)
                    )
                ).all()
            )
            turn = await session.get(Turn, turn_id)
        for event in events:
            after = event.sequence
            body = {
                "event_id": str(event.id),
                "turn_id": str(turn_id),
                "sequence": event.sequence,
                "timestamp": event.created_at.isoformat(),
                "type": event.event_type,
                "payload": event.payload,
            }
            yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(body)}\n\n"
        if turn is None or (turn.state in {"completed", "failed", "cancelled"} and not events):
            return
        idle_ticks += 1
        if idle_ticks % 20 == 0:
            yield ": heartbeat\n\n"
        await asyncio.sleep(0.25)
