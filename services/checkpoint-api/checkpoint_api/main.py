import asyncio
import base64
import binascii
import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Annotated, Literal, TypedDict
from uuid import UUID

import asyncpg
import nats
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from checkpoint_api.auth import RunCapability, authenticated_capability
from checkpoint_api.messaging import publish_loop
from checkpoint_api.problems import CheckpointProblem, problem_response
from checkpoint_api.readiness import check_dependencies
from checkpoint_api.store import CheckpointRecord, get_checkpoint, list_checkpoints, put_checkpoint

SERVICE_NAME = "checkpoint-api"
SERVICE_VERSION = "0.2.0"
MAX_PAYLOAD_BYTES = 1024 * 1024


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class PutCheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int = Field(ge=1)
    expected_version: int = Field(ge=0)
    serialization_version: str = Field(min_length=1, max_length=32)
    payload: str = Field(max_length=1_398_104)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CheckpointMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_id: UUID
    thread_id: UUID
    version: int
    serialization_version: str
    payload_sha256: str
    created_at: datetime


class CheckpointResponse(CheckpointMetadataResponse):
    payload: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    if pool is None:
        raise RuntimeError("database pool creation failed")
    app.state.pool = pool
    client = await nats.connect(
        os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"]
    )
    publisher = asyncio.create_task(publish_loop(pool, client.jetstream()))
    try:
        yield
    finally:
        publisher.cancel()
        with suppress(asyncio.CancelledError):
            await publisher
        await client.close()
        await pool.close()


app = FastAPI(title="Checkpoint API", version=SERVICE_VERSION, lifespan=lifespan)


@app.exception_handler(CheckpointProblem)
async def checkpoint_problem_handler(request: Request, error: CheckpointProblem) -> JSONResponse:
    return problem_response(request, error)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return problem_response(
        request,
        CheckpointProblem(
            422,
            "request_invalid",
            "The request does not match the API contract",
            details={"error_count": len(error.errors())},
        ),
    )


def health_response() -> HealthResponse:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return health_response()


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    dependencies=[Depends(check_dependencies)],
)
async def ready() -> HealthResponse:
    return health_response()


def authorize(capability: RunCapability, thread_id: UUID, operation: str) -> None:
    if capability.thread_id != thread_id or operation not in capability.operations:
        raise CheckpointProblem(403, "checkpoint_forbidden", "Checkpoint namespace is forbidden")


def metadata(record: CheckpointRecord) -> CheckpointMetadataResponse:
    return CheckpointMetadataResponse(
        checkpoint_id=record.checkpoint_id,
        thread_id=record.thread_id,
        version=record.version,
        serialization_version=record.serialization_version,
        payload_sha256=record.payload_sha256,
        created_at=record.created_at,
    )


@app.get("/v1/threads/{thread_id}/checkpoints", response_model=list[CheckpointMetadataResponse])
async def checkpoint_list(
    thread_id: UUID,
    capability: Annotated[RunCapability, Depends(authenticated_capability)],
) -> list[CheckpointMetadataResponse]:
    authorize(capability, thread_id, "checkpoint:read")
    return [metadata(item) for item in await list_checkpoints(app.state.pool, thread_id)]


@app.get("/v1/threads/{thread_id}/checkpoints/{checkpoint_id}", response_model=CheckpointResponse)
async def checkpoint_get(
    thread_id: UUID,
    checkpoint_id: UUID,
    capability: Annotated[RunCapability, Depends(authenticated_capability)],
) -> CheckpointResponse:
    authorize(capability, thread_id, "checkpoint:read")
    item = await get_checkpoint(app.state.pool, thread_id, checkpoint_id)
    return CheckpointResponse(
        **metadata(item).model_dump(), payload=base64.b64encode(item.payload).decode()
    )


@app.put(
    "/v1/threads/{thread_id}/checkpoints/{checkpoint_id}", response_model=CheckpointMetadataResponse
)
async def checkpoint_put(
    thread_id: UUID,
    checkpoint_id: UUID,
    body: PutCheckpointRequest,
    capability: Annotated[RunCapability, Depends(authenticated_capability)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> CheckpointMetadataResponse:
    authorize(capability, thread_id, "checkpoint:write")
    if (body.run_id, body.attempt_id, body.lease_epoch) != (
        capability.run_id,
        capability.attempt_id,
        capability.lease_epoch,
    ):
        raise CheckpointProblem(
            403, "capability_claim_mismatch", "Request does not match capability"
        )
    try:
        payload = base64.b64decode(body.payload, validate=True)
    except (binascii.Error, ValueError):
        raise CheckpointProblem(422, "payload_invalid", "Checkpoint payload is invalid") from None
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise CheckpointProblem(413, "payload_too_large", "Checkpoint payload exceeds the limit")
    if hashlib.sha256(payload).hexdigest() != body.payload_sha256:
        raise CheckpointProblem(
            422, "payload_hash_mismatch", "Checkpoint payload hash does not match"
        )
    item = await put_checkpoint(
        app.state.pool,
        capability=capability,
        checkpoint_id=checkpoint_id,
        expected_version=body.expected_version,
        serialization_version=body.serialization_version,
        payload=payload,
        payload_sha256=body.payload_sha256,
        idempotency_key=idempotency_key,
    )
    return metadata(item)
