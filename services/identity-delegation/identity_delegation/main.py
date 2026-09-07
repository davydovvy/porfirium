from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, TypedDict
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from identity_delegation.policy import RunGrant, authorize_model, authorize_tool
from identity_delegation.problems import DelegationProblem, problem_response
from identity_delegation.readiness import check_dependencies
from identity_delegation.store import GrantRecord, create_grant, get_grant, revoke_grant
from identity_delegation.tokens import issue_token, verify_token

SERVICE_NAME = "identity-delegation"
SERVICE_VERSION = "0.2.0"
MCP_AUDIENCE = "porfirium-mcp-gateway"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class CreateGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    release_id: UUID
    maximum_scopes: list[str] = Field(max_length=64)


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant_id: UUID
    conversation_id: UUID
    release_id: UUID
    maximum_scopes: list[str]
    expires_at: datetime
    revoked: bool


class ExchangeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int = Field(ge=1)
    audience: Literal["porfirium-mcp-gateway"]
    scopes: list[str] = Field(max_length=64)


class DelegatedToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: datetime
    audience: Literal["porfirium-mcp-gateway"] = MCP_AUDIENCE
    scopes: list[str]


class ModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=128)


class AuthorizationResult(BaseModel):
    authorized: Literal[True] = True


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


app = FastAPI(title="Identity Delegation", version=SERVICE_VERSION, lifespan=lifespan)


@app.exception_handler(DelegationProblem)
async def delegation_problem_handler(request: Request, error: DelegationProblem) -> JSONResponse:
    return problem_response(request, error)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    return problem_response(request, DelegationProblem(422, "request_invalid", "Invalid request"))


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


def grant_response(item: GrantRecord) -> Grant:
    return Grant(
        grant_id=item.grant_id,
        conversation_id=item.conversation_id,
        release_id=item.release_id,
        maximum_scopes=item.maximum_scopes,
        expires_at=item.expires_at,
        revoked=item.revoked_at is not None,
    )


def user_identity(x_user_id: Annotated[UUID, Header(alias="X-User-ID")]) -> UUID:
    return x_user_id


def signing_secret() -> str:
    value = os.environ.get("DELEGATION_SIGNING_SECRET")
    if not value:
        raise DelegationProblem(503, "token_issuer_unavailable", "Token issuer is unavailable")
    return value


def bearer(value: str | None) -> str:
    if not value or not value.startswith("Bearer "):
        raise DelegationProblem(401, "authentication_required", "Bearer token is required")
    return value[7:]


def run_grant(authorization: str | None) -> RunGrant:
    token = bearer(authorization)
    try:
        claims = verify_token(token, signing_secret(), "porfirium-gateway-policy")
    except DelegationProblem:
        capability_secret = os.environ.get("RUN_CAPABILITY_SECRET")
        if not capability_secret:
            raise
        claims = verify_token(token, capability_secret, "agent-runtime-api")
    try:
        return RunGrant(
            str(UUID(claims["run_id"])),
            str(UUID(claims["attempt_id"])),
            int(claims["lease_epoch"]),
            frozenset(claims["models"]),
            frozenset(claims["tools"]),
            bool(claims.get("cancelled", False)),
        )
    except (KeyError, TypeError, ValueError):
        raise DelegationProblem(401, "token_invalid", "Token is invalid") from None


@app.post("/v1/delegation-grants", response_model=Grant, status_code=201)
async def grant_create(
    body: CreateGrant,
    user_id: Annotated[UUID, Depends(user_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> Grant:
    if len(set(body.maximum_scopes)) != len(body.maximum_scopes):
        raise DelegationProblem(422, "scopes_invalid", "Scopes must be unique")
    item = await create_grant(
        app.state.pool,
        user_id=user_id,
        idempotency_key=idempotency_key,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        **body.model_dump(),
    )
    return grant_response(item)


async def exchange_token(
    grant_id: UUID,
    body: ExchangeGrant,
    run_authorization: str | None,
    run_capability: str | None = None,
) -> DelegatedToken:
    capability_exchange = run_capability is not None
    if capability_exchange:
        capability_secret = os.environ.get("RUN_CAPABILITY_SECRET")
        if not capability_secret:
            raise DelegationProblem(
                503, "token_issuer_unavailable", "Token issuer is unavailable"
            )
        claims = verify_token(
            bearer(run_capability), capability_secret, "agent-runtime-api"
        )
    else:
        claims = verify_token(bearer(run_authorization), signing_secret(), "identity-delegation")
    expected = (str(grant_id), str(body.run_id), str(body.attempt_id), body.lease_epoch)
    actual = (
        claims.get("delegation_grant_id") if capability_exchange else claims.get("grant_id"),
        claims.get("run_id"),
        claims.get("attempt_id"),
        claims.get("lease_epoch"),
    )
    active = claims.get("active") is True or capability_exchange
    if actual != expected or not active or claims.get("cancelled") is True:
        raise DelegationProblem(403, "run_binding_invalid", "Active run binding is invalid")
    item = await get_grant(app.state.pool, grant_id)
    now = datetime.now(UTC)
    if item.revoked_at is not None or item.expires_at <= now:
        raise DelegationProblem(403, "grant_inactive", "Delegation grant is inactive")
    if str(item.release_id) != claims.get("release_id"):
        raise DelegationProblem(403, "release_binding_invalid", "Release binding is invalid")
    if capability_exchange:
        granted_scopes = {f"tool:{tool}" for tool in claims.get("tools", [])}
        if not set(body.scopes) <= granted_scopes:
            raise DelegationProblem(403, "scope_not_granted", "Tool is not granted to this run")
    effective = sorted(set(body.scopes) & set(item.maximum_scopes))
    if set(effective) != set(body.scopes):
        raise DelegationProblem(403, "scope_not_delegated", "Requested scope was not delegated")
    expires_at = min(item.expires_at, now + timedelta(minutes=5))
    token = issue_token(
        {
            "aud": MCP_AUDIENCE,
            "sub": str(item.user_id),
            "grant_id": str(grant_id),
            "run_id": str(body.run_id),
            "attempt_id": str(body.attempt_id),
            "lease_epoch": body.lease_epoch,
            "scopes": effective,
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        signing_secret(),
    )
    return DelegatedToken(access_token=token, expires_at=expires_at, scopes=effective)


@app.post("/v1/delegation-grants/{grant_id}:exchange", response_model=DelegatedToken)
@app.post("/v1/delegation-grants/{grant_id}:renew", response_model=DelegatedToken)
async def grant_exchange(
    grant_id: UUID,
    body: ExchangeGrant,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
    authorization: Annotated[str | None, Header()] = None,
    run_capability: Annotated[str | None, Header(alias="X-Run-Capability")] = None,
) -> DelegatedToken:
    return await exchange_token(grant_id, body, authorization, run_capability)


@app.post("/v1/delegation-grants/{grant_id}:revoke", status_code=204)
async def grant_revoke(
    grant_id: UUID,
    user_id: Annotated[UUID, Depends(user_identity)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> Response:
    item = await get_grant(app.state.pool, grant_id)
    if item.user_id != user_id:
        raise DelegationProblem(404, "grant_not_found", "Delegation grant was not found")
    await revoke_grant(app.state.pool, grant_id)
    return Response(status_code=204)


@app.post("/v1/gateway/models:authorize", response_model=AuthorizationResult)
async def model_authorize(
    body: ModelCall, authorization: Annotated[str | None, Header()] = None
) -> AuthorizationResult:
    authorize_model(run_grant(authorization), body.model)
    return AuthorizationResult()


@app.post("/v1/gateway/tools:authorize", response_model=AuthorizationResult)
async def tool_authorize(
    body: ToolCall,
    authorization: Annotated[str | None, Header(alias="X-Run-Authorization")] = None,
    delegated_authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AuthorizationResult:
    run = run_grant(authorization)
    delegated = verify_token(bearer(delegated_authorization), signing_secret(), MCP_AUDIENCE)
    if (
        delegated.get("run_id") != run.run_id
        or delegated.get("attempt_id") != run.attempt_id
        or delegated.get("lease_epoch") != run.lease_epoch
    ):
        raise DelegationProblem(403, "token_run_mismatch", "Delegated token belongs to another run")
    authorize_tool(run, body.tool, frozenset(delegated.get("scopes", [])))
    return AuthorizationResult()
