from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from portal_bff.auth import CurrentIdentity, Identity
from portal_bff.readiness import check_dependencies

SERVICE_NAME = "portal-bff"
SERVICE_VERSION = "0.1.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    release_id: UUID


class CreateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=20_000)


class InputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: Any


class PublishRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    image: str = Field(min_length=1, max_length=512)
    provenance: dict[str, Any]


class SelectDefaultRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: UUID


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=2))
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="Portal BFF", version=SERVICE_VERSION, lifespan=lifespan)


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


def _url(service: str, path: str) -> str:
    return f"{os.environ[service].rstrip('/')}{path}"


def _user_headers(identity: Identity, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"X-User-ID": str(identity.subject)}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _registry_authorization(request: Request, identity: Identity) -> str:
    try:
        response = await request.app.state.client.post(
            os.environ["OIDC_TOKEN_URL"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": os.environ["OIDC_CLIENT_ID"],
                "client_secret": os.environ["OIDC_CLIENT_SECRET"],
                "subject_token": identity.token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": os.environ.get("AGENT_REGISTRY_AUDIENCE", "agent-registry"),
            },
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("missing access token")
        return f"Bearer {token}"
    except (KeyError, TypeError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=503, detail="Identity delegation unavailable") from error


async def _request(
    request: Request,
    method: str,
    service: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        response = await request.app.state.client.request(
            method, _url(service, path), headers=headers, json=body
        )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Target service unavailable") from error
    return response


def _forward(response: httpx.Response) -> Response:
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


@app.get("/api/v1/me")
async def me(identity: CurrentIdentity) -> dict[str, Any]:
    roles = set(identity.roles)
    return {
        "id": str(identity.subject),
        "username": identity.username,
        "display_name": identity.display_name,
        "roles": identity.roles,
        "capabilities": {
            "agent_authoring": bool(
                roles & {"genai-agent-author", "genai-agent-publisher"}
            ),
            "agent_publication": "genai-agent-publisher" in roles,
        },
    }


@app.get("/api/v1/agents")
async def agents(request: Request, identity: CurrentIdentity) -> Response:
    authorization = await _registry_authorization(request, identity)
    response = await _request(
        request,
        "GET",
        "AGENT_REGISTRY_URL",
        "/v1/agents",
        headers={"Authorization": authorization},
    )
    return _forward(response)


def _require_role(identity: Identity, role: str) -> None:
    if role not in identity.roles:
        raise HTTPException(status_code=403, detail="Operation is not permitted")


@app.post("/api/v1/releases", status_code=201)
async def publish_release(
    body: PublishRelease,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    _require_role(identity, "genai-agent-publisher")
    return _forward(await _request(
        request,
        "POST",
        "AGENT_REGISTRY_URL",
        "/v1/releases",
        headers={
            "Authorization": await _registry_authorization(request, identity),
            "Idempotency-Key": idempotency_key,
        },
        body=body.model_dump(),
    ))


@app.post("/api/v1/agents/{agent_id}/default-release")
async def select_default_release(
    agent_id: str,
    body: SelectDefaultRelease,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    _require_role(identity, "genai-agent-registry-admin")
    return _forward(await _request(
        request,
        "POST",
        "AGENT_REGISTRY_URL",
        f"/v1/agents/{agent_id}/default-release",
        headers={
            "Authorization": await _registry_authorization(request, identity),
            "Idempotency-Key": idempotency_key,
        },
        body=body.model_dump(mode="json"),
    ))


@app.post("/api/v1/releases/{release_id}:deprecate")
async def deprecate_release(
    release_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    _require_role(identity, "genai-agent-registry-admin")
    return _forward(await _request(
        request,
        "POST",
        "AGENT_REGISTRY_URL",
        f"/v1/releases/{release_id}:deprecate",
        headers={
            "Authorization": await _registry_authorization(request, identity),
            "Idempotency-Key": idempotency_key,
        },
    ))


@app.get("/api/v1/conversations")
async def conversations(request: Request, identity: CurrentIdentity) -> Response:
    return _forward(
        await _request(
            request, "GET", "CONVERSATION_SERVICE_URL", "/v1/conversations",
            headers=_user_headers(identity)
        )
    )


@app.post("/api/v1/conversations", status_code=201)
async def create_conversation(
    body: CreateConversation,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    response = await _request(
        request,
        "POST",
        "CONVERSATION_SERVICE_URL",
        "/v1/conversations",
        headers=_user_headers(identity, idempotency_key),
        body={
            "title": body.title,
            "release_id": str(body.release_id),
            "thread_id": str(
                uuid5(NAMESPACE_URL, f"porfirium:{identity.subject}:conversation:{idempotency_key}")
            ),
        },
    )
    return _forward(response)


@app.get("/api/v1/conversations/{conversation_id}")
async def conversation(
    conversation_id: UUID, request: Request, identity: CurrentIdentity
) -> Response:
    response = await _request(
        request, "GET", "CONVERSATION_SERVICE_URL", f"/v1/conversations/{conversation_id}",
        headers=_user_headers(identity)
    )
    if response.status_code != 200:
        return _forward(response)
    projection = response.json()
    messages = projection.get("messages", [])
    if messages:
        latest_run_id = messages[-1].get("run_id")
        terminal = any(
            message.get("run_id") == latest_run_id
            and message.get("role") == "assistant"
            and message.get("status") in {"completed", "failed", "interrupted"}
            for message in messages
        )
        if latest_run_id and not terminal:
            run = await _request(
                request, "GET", "AGENT_RUNNER_URL", f"/v1/runs/{latest_run_id}"
            )
            if run.status_code != 200:
                projection["active_run"] = {"run_id": latest_run_id, "state": "requested"}
            elif run.json().get("state") in {
                "accepted",
                "scheduled",
                "starting",
                "running",
                "suspending",
                "waiting_for_input",
                "completion_reconciling",
                "cancelling",
            }:
                projection["active_run"] = run.json()
    return JSONResponse(projection)


@app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
async def create_message(
    conversation_id: UUID,
    body: CreateMessage,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    owned = await _request(
        request, "GET", "CONVERSATION_SERVICE_URL", f"/v1/conversations/{conversation_id}",
        headers=_user_headers(identity)
    )
    if owned.status_code != 200:
        return _forward(owned)
    release_id = owned.json()["release_id"]
    release = await _request(
        request,
        "GET",
        "AGENT_REGISTRY_URL",
        f"/v1/releases/{release_id}",
        headers={"Authorization": await _registry_authorization(request, identity)},
    )
    if release.status_code != 200:
        return _forward(release)
    tools = release.json().get("manifest", {}).get("spec", {}).get("tools", [])
    if (
        not isinstance(tools, list)
        or len(tools) > 64
        or any(not isinstance(tool, str) or not tool or len(tool) > 128 for tool in tools)
    ):
        raise HTTPException(status_code=502, detail="Registry release tools are invalid")
    grant = await _request(
        request,
        "POST",
        "IDENTITY_DELEGATION_URL",
        "/v1/delegation-grants",
        headers=_user_headers(
            identity,
            str(uuid5(NAMESPACE_URL, f"porfirium:{conversation_id}:grant:{idempotency_key}")),
        ),
        body={
            "conversation_id": str(conversation_id),
            "release_id": release_id,
            "maximum_scopes": [f"tool:{tool}" for tool in tools],
        },
    )
    if grant.status_code != 201:
        return _forward(grant)
    run_id = uuid5(NAMESPACE_URL, f"porfirium:{conversation_id}:run:{idempotency_key}")
    message_id = uuid5(NAMESPACE_URL, f"porfirium:{conversation_id}:message:{idempotency_key}")
    response = await _request(
        request,
        "POST",
        "CONVERSATION_SERVICE_URL",
        f"/v1/conversations/{conversation_id}/messages",
        headers=_user_headers(identity, idempotency_key),
        body={"message_id": str(message_id), "run_id": str(run_id), "content": body.content,
              "delegation_grant_id": grant.json()["grant_id"]},
    )
    return _forward(response)


@app.post("/api/v1/input-requests/{input_request_id}/responses", status_code=202)
async def respond_to_input(
    input_request_id: UUID,
    body: InputResponse,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    return _forward(await _request(
        request, "POST", "CONVERSATION_SERVICE_URL",
        f"/v1/input-requests/{input_request_id}/responses",
        headers=_user_headers(identity, idempotency_key),
        body={
            "run_id": str(
                uuid5(NAMESPACE_URL, f"porfirium:{input_request_id}:run:{idempotency_key}")
            ),
            "response": body.response,
        },
    ))


@app.post("/api/v1/conversations/{conversation_id}/runs/{run_id}:cancel", status_code=202)
async def cancel_run(
    conversation_id: UUID,
    run_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> Response:
    owned = await _request(
        request, "GET", "CONVERSATION_SERVICE_URL", f"/v1/conversations/{conversation_id}",
        headers=_user_headers(identity)
    )
    if owned.status_code != 200:
        return _forward(owned)
    run_ids = {message.get("run_id") for message in owned.json().get("messages", [])}
    run_ids.update(item.get("run_id") for item in owned.json().get("input_requests", []))
    if str(run_id) not in run_ids:
        raise HTTPException(status_code=404, detail="Run was not found")
    return _forward(await _request(
        request, "POST", "AGENT_RUNNER_URL", f"/v1/runs/{run_id}:cancel",
        headers={"Idempotency-Key": idempotency_key}
    ))


@app.get("/api/v1/conversations/{conversation_id}/events")
async def events(
    conversation_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> StreamingResponse:
    upstream_request = request.app.state.client.build_request(
        "GET",
        _url("CONVERSATION_SERVICE_URL", f"/v1/conversations/{conversation_id}/events"),
        headers={**_user_headers(identity), "Last-Event-ID": str(last_event_id)},
    )
    try:
        upstream = await request.app.state.client.send(upstream_request, stream=True)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=503, detail="Target service unavailable") from error
    if upstream.status_code != 200:
        content = await upstream.aread()
        await upstream.aclose()
        return StreamingResponse(
            iter([content]), status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/problem+json")
        )

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
