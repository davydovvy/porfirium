import asyncio
import logging
import uuid

import httpx
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from .agent import AgentWorkflowV1
from .chat import append_event
from .config import settings
from .db import session_factory
from .models import Message, Turn, now_utc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@activity.defn(name="mark_agent_running")
async def mark_agent_running(turn_id: str) -> None:
    identifier = uuid.UUID(turn_id)
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state in {"completed", "cancelled"}:
            return
        turn.state = "running"
        turn.updated_at = now_utc()
        await session.commit()
    await append_event(
        identifier, "agent.status", {"status": "planning", "label": "Planning response"}
    )


@activity.defn(name="generate_agent_response")
async def generate_agent_response(turn_id: str) -> str:
    identifier = uuid.UUID(turn_id)
    await append_event(
        identifier, "agent.status", {"status": "generating", "label": "Generating response"}
    )
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None:
            raise ValueError("Turn no longer exists")
        history = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == turn.conversation_id)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )
        body = {
            "model": f"yandex/{settings.llm_model}",
            "input": [
                {"role": item.role, "content": item.content} for item in history if item.content
            ],
            "instructions": (
                "You are Porfirium's durable agent. Answer the user clearly and completely. "
                "Do not claim to use tools; tools are introduced in a later phase."
            ),
            "max_output_tokens": settings.llm_max_output_tokens,
            "tools": [],
            "tool_choice": "none",
            "metadata": {
                "conversation_id": str(turn.conversation_id),
                "turn_id": str(turn.id),
                "user_id": str(turn.owner_id),
                "correlation_id": turn.correlation_id,
                "execution": "temporal-agent-v1",
            },
        }
        correlation_id = turn.correlation_id
    activity.heartbeat("calling-model")
    parent_span_id = uuid.uuid4().hex[:16]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10)
    ) as client:
        response = await client.post(
            f"{settings.bifrost_url}/v1/responses",
            json=body,
            headers={
                "x-request-id": correlation_id,
                "traceparent": f"00-{correlation_id}-{parent_span_id}-01",
            },
        )
        response.raise_for_status()
        payload = response.json()
    activity.heartbeat("model-complete")
    if any(item.get("type") == "function_call" for item in payload.get("output", [])):
        logger.warning(
            "Rejected unexpected Phase 3 tool call correlation_id=%s turn_id=%s",
            correlation_id,
            identifier,
        )
        return (
            "Tools are not available in Agent mode yet. Phase 3 provides durable no-tool "
            "responses; the platform information and MTG tools arrive in Phase 4."
        )
    text = payload.get("output_text")
    if not text:
        text = "".join(
            str(part.get("text", ""))
            for item in payload.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    if not text:
        raise ValueError("Model returned no output text")
    return str(text)


@activity.defn(name="complete_agent_turn")
async def complete_agent_turn(value: dict[str, str]) -> None:
    identifier = uuid.UUID(value["turn_id"])
    content = value["content"]
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state == "cancelled":
            return
        message = await session.scalar(
            select(Message).where(Message.turn_id == identifier, Message.role == "assistant")
        )
        if message is None:
            message = Message(
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                role="assistant",
                content=content,
                status="complete",
            )
            session.add(message)
        else:
            message.content = content
            message.status = "complete"
        turn.state = "completed"
        turn.updated_at = now_utc()
        await session.commit()
        message_id = message.id
    await append_event(
        identifier, "agent.status", {"status": "completed", "label": "Response complete"}
    )
    await append_event(
        identifier, "turn.completed", {"message_id": str(message_id), "content": content}
    )


@activity.defn(name="fail_agent_turn")
async def fail_agent_turn(turn_id: str) -> None:
    identifier = uuid.UUID(turn_id)
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state in {"completed", "cancelled"}:
            return
        turn.state = "failed"
        turn.error_code = "agent_execution_failed"
        turn.updated_at = now_utc()
        await session.commit()
        correlation_id = turn.correlation_id
    await append_event(
        identifier,
        "turn.failed",
        {
            "code": "agent_execution_failed",
            "message": "The durable agent could not complete this run.",
            "correlation_id": correlation_id,
        },
    )


async def run() -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentWorkflowV1],
        activities=[
            mark_agent_running,
            generate_agent_response,
            complete_agent_turn,
            fail_agent_turn,
        ],
    )
    logger.info("Agent worker listening task_queue=%s", settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
