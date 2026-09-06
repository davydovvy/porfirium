from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import nats
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from conversation_service.domain import MemoryStore, input_json, message_json
from conversation_service.messaging import consume_runtime_events, publish_pending
from conversation_service.problems import ConversationProblem, problem_response
from conversation_service.readiness import check_dependencies

SERVICE_NAME = "conversation-service"
SERVICE_VERSION = "0.2.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    release_id: UUID
    thread_id: UUID
    configuration_revision_id: UUID | None = None


class CreateUserMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: UUID
    run_id: UUID
    content: str = Field(min_length=1, max_length=20_000)
    delegation_grant_id: UUID


class InputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    response: Any


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from conversation_service.store import PostgresStore

    store = await PostgresStore.connect()
    client = await nats.connect(
        os.environ["NATS_URL"],
        user=os.environ["NATS_USER"],
        password=os.environ["NATS_PASSWORD"],
    )
    jetstream = client.jetstream()
    conversation_subscription = await jetstream.subscribe(
        "porfirium.conversation.event.>",
        durable="conversation-service-events-v1",
        manual_ack=True,
    )
    delta_subscription = await jetstream.subscribe(
        "porfirium.message.delta.>",
        durable="conversation-service-deltas-v1",
        manual_ack=True,
    )

    async def publish_loop() -> None:
        while True:
            await publish_pending(store.pool, jetstream)
            await asyncio.sleep(0.05)

    tasks = [
        asyncio.create_task(publish_loop()),
        asyncio.create_task(consume_runtime_events(store, conversation_subscription)),
        asyncio.create_task(consume_runtime_events(store, delta_subscription)),
    ]
    app.state.store = store
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await client.close()
        await store.close()


app = FastAPI(title="Conversation Service", version=SERVICE_VERSION, lifespan=lifespan)
app.state.store = MemoryStore()


@app.exception_handler(ConversationProblem)
async def conversation_problem_handler(
    request: Request, error: ConversationProblem
) -> JSONResponse:
    return problem_response(request, error)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return problem_response(request, ConversationProblem(422, "request_invalid", "Invalid request"))


def owner_id(x_user_id: Annotated[UUID, Header(alias="X-User-ID")]) -> UUID:
    return x_user_id


def health_response() -> HealthResponse:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return health_response()


@app.get("/health/ready", response_model=HealthResponse, dependencies=[Depends(check_dependencies)])
async def ready() -> HealthResponse:
    return health_response()


def conversation_json(item: Any) -> dict[str, Any]:
    return {
        "conversation_id": str(item.conversation_id),
        "thread_id": str(item.thread_id),
        "release_id": str(item.release_id),
        "configuration_revision_id": (
            str(item.configuration_revision_id) if item.configuration_revision_id else None
        ),
        "title": item.title,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@app.post("/v1/conversations", status_code=201)
async def create_conversation(
    body: CreateConversation,
    user_id: Annotated[UUID, Depends(owner_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, Any]:
    item = await app.state.store.create_conversation(user_id, idempotency_key, body.model_dump())
    return conversation_json(item)


@app.get("/v1/conversations")
async def list_conversations(
    user_id: Annotated[UUID, Depends(owner_id)],
) -> list[dict[str, Any]]:
    return [conversation_json(item) for item in await app.state.store.list_conversations(user_id)]


@app.get("/v1/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, user_id: Annotated[UUID, Depends(owner_id)]
) -> dict[str, Any]:
    projection = await app.state.store.projection(user_id, conversation_id)
    conversation = projection["conversation"]
    return {
        **conversation_json(conversation),
        "messages": [message_json(item) for item in projection["messages"]],
        "input_requests": [input_json(item) for item in projection["input_requests"]],
        "last_sequence": conversation.last_sequence,
    }


@app.post("/v1/conversations/{conversation_id}/messages", status_code=202)
async def create_user_message(
    conversation_id: UUID,
    body: CreateUserMessage,
    user_id: Annotated[UUID, Depends(owner_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, Any]:
    message, sequence = await app.state.store.create_message(
        user_id, conversation_id, idempotency_key, body.model_dump()
    )
    return {
        "message_id": str(message.message_id),
        "run_id": str(message.run_id),
        "conversation_sequence": sequence,
    }


@app.post("/v1/input-requests/{input_request_id}/responses", status_code=202)
async def answer_input_request(
    input_request_id: UUID,
    body: InputResponse,
    user_id: Annotated[UUID, Depends(owner_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, Any]:
    message_id, sequence = await app.state.store.answer_input(
        user_id, input_request_id, idempotency_key, body.run_id, body.response
    )
    return {
        "message_id": str(message_id),
        "run_id": str(body.run_id),
        "conversation_sequence": sequence,
    }


def sse(event: Any) -> str:
    data = json.dumps(event.data, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"


@app.get("/v1/conversations/{conversation_id}/events")
async def conversation_events(
    request: Request,
    conversation_id: UUID,
    user_id: Annotated[UUID, Depends(owner_id)],
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> StreamingResponse:
    initial = await app.state.store.replay(user_id, conversation_id, last_event_id)

    async def stream() -> AsyncIterator[str]:
        cursor, pending = last_event_id, initial
        while True:
            for event in pending:
                cursor = event.sequence
                yield sse(event)
            if await request.is_disconnected():
                return
            pending = await app.state.store.replay(user_id, conversation_id, cursor)
            if not pending:
                yield ": keepalive\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/internal/v1/runtime-events", status_code=202)
async def project_runtime_event(
    envelope: dict[str, Any],
) -> dict[str, int | bool | None]:
    sequence = await app.state.store.project(envelope)
    return {"accepted": sequence is not None, "conversation_sequence": sequence}
