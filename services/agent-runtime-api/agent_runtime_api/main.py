from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Literal, TypedDict

import asyncpg
import grpc
import httpx
import nats
from fastapi import Depends, FastAPI

from agent_runtime_api.model_gateway import ModelGateway
from agent_runtime_api.outbox import publish_pending
from agent_runtime_api.readiness import check_dependencies
from agent_runtime_api.runtime import RuntimeService, add_runtime_service

SERVICE_NAME = "agent-runtime-api"
SERVICE_VERSION = "0.1.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


async def _publish_loop(pool, jetstream) -> None:
    while True:
        await publish_pending(pool, jetstream)
        await asyncio.sleep(0.05)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    nats_client = await nats.connect(
        os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"]
    )
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 16 * 1024),
            ("grpc.max_send_message_length", 16 * 1024),
        ]
    )
    model_client = httpx.AsyncClient(
        timeout=httpx.Timeout(float(os.environ.get("MODEL_TIMEOUT_SECONDS", "120")), connect=5)
    )
    model_gateway = ModelGateway(model_client, os.environ["MODEL_GATEWAY_URL"])
    add_runtime_service(server, RuntimeService(pool, model_gateway))
    server.add_insecure_port(f"0.0.0.0:{os.environ.get('RUNTIME_GRPC_PORT', '50051')}")
    await server.start()
    publisher = asyncio.create_task(_publish_loop(pool, nats_client.jetstream()))
    app.state.pool = pool
    try:
        yield
    finally:
        publisher.cancel()
        with suppress(asyncio.CancelledError):
            await publisher
        await server.stop(grace=3)
        await nats_client.close()
        await model_client.aclose()
        await pool.close()


app = FastAPI(title="Agent Runtime API", version=SERVICE_VERSION, lifespan=lifespan)


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
