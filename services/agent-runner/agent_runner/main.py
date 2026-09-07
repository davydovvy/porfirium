from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal, TypedDict
from uuid import UUID

import asyncpg
import httpx
import nats
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from agent_runner.container import PodmanBackend
from agent_runner.messaging import consume_admissions, consume_completion_events, publish_loop
from agent_runner.models import RunAdmission, RunResponse
from agent_runner.readiness import check_dependencies
from agent_runner.registry import (
    ClientCredentialsTokenProvider,
    RegistryClient,
    RegistryResolutionError,
)
from agent_runner.service import RunnerError, RunnerService
from agent_runner.specification import load_public_keys, verify_specification

SERVICE_NAME = "agent-runner"
SERVICE_VERSION = "0.2.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


async def _scheduler(app: FastAPI) -> None:
    while True:
        try:
            rows = await app.state.pool.fetch(
                "SELECT run_id FROM runs WHERE state IN ('accepted','scheduled') "
                "AND active_attempt_id IS NULL ORDER BY created_at LIMIT 10"
            )
            for row in rows:
                with suppress(Exception):
                    await app.state.runner.schedule(row["run_id"])
            await app.state.runner.reconcile()
        finally:
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    if pool is None:
        raise RuntimeError("database pool creation failed")
    client = httpx.AsyncClient(timeout=httpx.Timeout(5, connect=2))
    app.state.pool = pool
    registry_token = ClientCredentialsTokenProvider(
        client,
        os.environ.get("RUNNER_OIDC_TOKEN_URL", os.environ["OIDC_TOKEN_URL"]),
        os.environ["OIDC_CLIENT_ID"],
        os.environ["OIDC_CLIENT_SECRET"],
    )
    app.state.registry = RegistryClient(
        client, os.environ["AGENT_REGISTRY_URL"], registry_token
    )
    app.state.registry_public_keys = load_public_keys(os.environ["REGISTRY_RUN_PUBLIC_KEYS"])
    app.state.runner = RunnerService(
        pool, PodmanBackend(os.environ.get("RUNTIME_CONTAINER", "porfirium-agent-runtime-api")),
        capability_secret=os.environ["RUN_CAPABILITY_SECRET"],
        runtime_url=os.environ["AGENT_RUNTIME_URL"],
        attempt_timeout_seconds=int(os.environ.get("RUNNER_ATTEMPT_TIMEOUT_SECONDS", "300")),
        max_attempts=int(os.environ.get("RUNNER_MAX_ATTEMPTS", "3")),
    )
    app.state.verify_specification = lambda specification: verify_specification(
        specification, app.state.registry_public_keys
    )
    nats_client = await nats.connect(
        os.environ["NATS_URL"], user=os.environ["NATS_USER"], password=os.environ["NATS_PASSWORD"]
    )
    jetstream = nats_client.jetstream()
    completion_subscription = await jetstream.subscribe(
        "porfirium.run.event.*", durable="agent-runner-completion-v1", manual_ack=True
    )
    message_subscription = await jetstream.subscribe(
        "porfirium.conversation.event.message_started",
        durable="agent-runner-visible-output-v1",
        manual_ack=True,
    )
    admission_subscription = await jetstream.subscribe(
        "porfirium.run.command.requested",
        durable="agent-runner-admission-v1",
        manual_ack=True,
    )
    scheduler = asyncio.create_task(_scheduler(app))
    messaging_tasks = [
        asyncio.create_task(publish_loop(pool, jetstream)),
        asyncio.create_task(consume_completion_events(app.state.runner, completion_subscription)),
        asyncio.create_task(consume_completion_events(app.state.runner, message_subscription)),
        asyncio.create_task(consume_admissions(app, admission_subscription)),
    ]
    try:
        yield
    finally:
        scheduler.cancel()
        for task in messaging_tasks:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler
        for task in messaging_tasks:
            with suppress(asyncio.CancelledError):
                await task
        await nats_client.close()
        await client.aclose()
        await pool.close()


app = FastAPI(title="Agent Runner", version=SERVICE_VERSION, lifespan=lifespan)


def health_response() -> HealthResponse:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.exception_handler(RunnerError)
async def runner_error_handler(request: Request, error: RunnerError) -> JSONResponse:
    statuses = {"run_not_found": 404, "idempotency_conflict": 409, "run_conflict": 409,
                "specification_invalid": 422, "specification_expired": 422}
    status = statuses.get(error.code, 500)
    return JSONResponse(
        {"type": f"urn:porfirium:problem:{error.code}", "title": error.code.replace("_", " "),
         "status": status, "code": error.code, "instance": str(request.url.path)},
        status_code=status, media_type="application/problem+json",
    )


@app.exception_handler(RegistryResolutionError)
async def registry_error_handler(request: Request, error: RegistryResolutionError) -> JSONResponse:
    return JSONResponse(
        {"type": "urn:porfirium:problem:registry_resolution_failed",
         "title": "Run specification resolution failed", "status": 503,
         "code": "registry_resolution_failed", "instance": str(request.url.path)},
        status_code=503, media_type="application/problem+json",
    )


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return health_response()


@app.get("/health/ready", response_model=HealthResponse, dependencies=[Depends(check_dependencies)])
async def ready() -> HealthResponse:
    return health_response()


@app.post("/v1/runs", response_model=RunResponse, status_code=202)
async def admit_run(
    body: RunAdmission, request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> RunResponse:
    specification = await request.app.state.registry.resolve(body, idempotency_key)
    verify_specification(specification, request.app.state.registry_public_keys)
    return await request.app.state.runner.admit(body, idempotency_key, specification)


@app.get("/v1/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID, request: Request) -> RunResponse:
    return await request.app.state.runner.get(run_id)


@app.post("/v1/runs/{run_id}:cancel", response_model=RunResponse, status_code=202)
async def cancel_run(
    run_id: UUID, request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> RunResponse:
    return await request.app.state.runner.cancel(run_id, idempotency_key)
