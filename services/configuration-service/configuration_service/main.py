from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID, uuid5

import asyncpg
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from configuration_service.domain import (
    content_digest,
    merge_layers,
    validate_bounded,
    validate_effective,
    verify_schema_digest,
)
from configuration_service.problems import ConfigurationProblem, problem_response
from configuration_service.readiness import check_dependencies
from configuration_service.store import RevisionRecord, create_revision, get_revision

SERVICE_NAME = "configuration-service"
SERVICE_VERSION = "0.2.0"
EFFECTIVE_NAMESPACE = UUID("23c75272-8ba5-4d45-8a20-6ad184257b44")


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class CreateRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: UUID
    scope: Literal["user", "conversation"]
    conversation_id: UUID | None = None
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    values: dict[str, Any]
    secret_references: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scope_matches_conversation(self) -> CreateRevision:
        if (self.scope == "conversation") != (self.conversation_id is not None):
            raise ValueError("conversation_id is required only for conversation scope")
        return self


class Revision(CreateRevision):
    revision_id: UUID
    created_at: datetime


class ResolveConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: UUID
    schema: dict[str, Any]
    schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_defaults: dict[str, Any]
    user_revision_id: UUID | None = None
    conversation_revision_id: UUID | None = None


class EffectiveConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_revision_id: UUID
    schema_digest: str
    values: dict[str, Any]
    secret_references: dict[str, Any]
    content_sha256: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    if pool is None:
        raise RuntimeError("database pool creation failed")
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Configuration Service", version=SERVICE_VERSION, lifespan=lifespan)


@app.exception_handler(ConfigurationProblem)
async def configuration_problem_handler(
    request: Request, error: ConfigurationProblem
) -> JSONResponse:
    return problem_response(request, error)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return problem_response(
        request, ConfigurationProblem(422, "request_invalid", "Invalid request")
    )


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


def revision_response(item: RevisionRecord) -> Revision:
    return Revision(
        revision_id=item.revision_id,
        release_id=item.release_id,
        scope=item.scope,
        conversation_id=item.conversation_id,
        schema_digest=item.schema_digest,
        values=item.values,
        secret_references=item.secret_references,
        created_at=item.created_at,
    )


@app.post("/v1/revisions", response_model=Revision, status_code=201)
async def revision_create(
    body: CreateRevision,
    user_id: Annotated[UUID, Depends(owner_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> Revision:
    validate_bounded(body.values)
    validate_bounded(body.secret_references)
    item = await create_revision(
        app.state.pool, owner_id=user_id, idempotency_key=idempotency_key, **body.model_dump()
    )
    return revision_response(item)


@app.get("/v1/revisions/{revision_id}", response_model=Revision)
async def revision_get(revision_id: UUID, user_id: Annotated[UUID, Depends(owner_id)]) -> Revision:
    return revision_response(await get_revision(app.state.pool, user_id, revision_id))


@app.post("/v1/effective-configurations:resolve", response_model=EffectiveConfiguration)
async def resolve(
    body: ResolveConfiguration,
    user_id: Annotated[UUID, Depends(owner_id)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> EffectiveConfiguration:
    verify_schema_digest(body.schema, body.schema_digest)
    validate_bounded(body.release_defaults)
    layers: list[dict[str, Any]] = [body.release_defaults]
    secrets: list[dict[str, Any]] = [{}]
    revision_ids: list[str] = []
    for revision_id, expected_scope in (
        (body.user_revision_id, "user"),
        (body.conversation_revision_id, "conversation"),
    ):
        if revision_id is None:
            continue
        item = await get_revision(app.state.pool, user_id, revision_id)
        if item.release_id != body.release_id or item.scope != expected_scope:
            raise ConfigurationProblem(409, "revision_incompatible", "Revision is incompatible")
        if item.schema_digest != body.schema_digest:
            raise ConfigurationProblem(
                409, "revision_schema_changed", "Revision schema has changed"
            )
        layers.append(item.values)
        secrets.append(item.secret_references)
        revision_ids.append(str(item.revision_id))
    values = merge_layers(*layers)
    secret_references = merge_layers(*secrets)
    validate_effective(body.schema, values)
    canonical = {
        "schema_digest": body.schema_digest,
        "values": values,
        "secret_references": secret_references,
        "source_revisions": revision_ids,
    }
    digest = content_digest(canonical)
    return EffectiveConfiguration(
        effective_revision_id=uuid5(EFFECTIVE_NAMESPACE, digest),
        schema_digest=body.schema_digest,
        values=values,
        secret_references=secret_references,
        content_sha256=digest,
    )
