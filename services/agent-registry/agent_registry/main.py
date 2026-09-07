from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import asyncpg
import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from agent_registry.access import (
    AccessError,
    AccessGrant,
    get_visible_release,
    grant_access,
    list_visible_agents,
    revoke_access,
)
from agent_registry.auth import (
    OidcAuthenticator,
    ServiceIdentity,
    authenticated_identity,
    require_admin,
    require_publisher,
    require_resolver,
)
from agent_registry.domain import PublicationValidationError, validate_publication
from agent_registry.evidence import EvidenceVerifier, load_publication_keys
from agent_registry.lifecycle import LifecycleError, deprecate_release, set_default_release
from agent_registry.problems import RegistryProblem, problem_response
from agent_registry.publication import PublicationError, publish_release
from agent_registry.readiness import check_dependencies
from agent_registry.resolution import (
    ResolutionError,
    ResolutionRequest,
    RunSpecificationSigner,
    load_run_signer,
    resolve_run_specification,
)

SERVICE_NAME = "agent-registry"
SERVICE_VERSION = "0.1.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


class PublishReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    image: str
    provenance: dict[str, Any]


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str
    agent_id: str
    version: str
    image: str
    manifest: dict[str, Any]
    status: Literal["published", "deprecated"]


class AgentSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    description: str
    default_release_id: str | None = None


class GrantAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: Literal["user", "group", "role"]
    subject_id: str
    permission: Literal["discover", "run", "publish", "admin"]


class AccessGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    agent_id: str
    subject_type: Literal["user", "group", "role"]
    subject_id: str
    permission: Literal["discover", "run", "publish", "admin"]
    revoked: bool


class SetDefaultReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: UUID


class ResolveRunSpecificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    user_id: UUID
    conversation_id: UUID
    thread_id: UUID
    release_id: UUID
    delegation_grant_id: UUID
    configuration_revision_id: UUID | None = None
    starting_checkpoint_id: UUID | None = None
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class SignedRunSpecificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification_id: UUID
    run_id: UUID
    payload: dict[str, Any]
    payload_sha256: str
    signature: str
    key_id: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = httpx.AsyncClient(timeout=httpx.Timeout(5, connect=2))
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    if pool is None:
        await client.aclose()
        raise RuntimeError("database pool creation failed")
    app.state.pool = pool
    introspection_url = os.environ.get("OIDC_INTROSPECTION_URL")
    oidc_client_id = os.environ.get("OIDC_CLIENT_ID")
    oidc_client_secret = os.environ.get("OIDC_CLIENT_SECRET")
    app.state.authenticator = None
    if introspection_url and oidc_client_id and oidc_client_secret:
        app.state.authenticator = OidcAuthenticator(
            client,
            introspection_url=introspection_url,
            client_id=oidc_client_id,
            client_secret=oidc_client_secret,
            audience=os.environ.get("OIDC_AUDIENCE", "agent-registry"),
        )
    app.state.evidence_verifier = None
    publication_keys = os.environ.get("REGISTRY_PUBLICATION_KEYS")
    if publication_keys:
        app.state.evidence_verifier = EvidenceVerifier(
            client,
            registry_url=os.environ["OCI_REGISTRY_URL"],
            registry_host=os.environ.get("OCI_REGISTRY_HOST", "registry:5000"),
            publication_keys=load_publication_keys(publication_keys),
            allowed_builders=frozenset(
                value.strip()
                for value in os.environ.get("REGISTRY_ALLOWED_BUILDERS", "").split(",")
                if value.strip()
            ),
        )
    app.state.run_signer = None
    signing_key_file = os.environ.get("REGISTRY_RUN_SIGNING_KEY_FILE")
    signing_key_id = os.environ.get("REGISTRY_RUN_SIGNING_KEY_ID")
    if signing_key_file and signing_key_id:
        app.state.run_signer = load_run_signer(
            signing_key_file,
            signing_key_id,
            int(os.environ.get("REGISTRY_RUN_SPECIFICATION_TTL_SECONDS", "300")),
        )
    try:
        yield
    finally:
        await pool.close()
        await client.aclose()


app = FastAPI(title="Agent Registry", version=SERVICE_VERSION, lifespan=lifespan)


@app.exception_handler(RegistryProblem)
async def registry_problem_handler(request: Request, error: RegistryProblem) -> JSONResponse:
    return problem_response(request, error)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    return problem_response(
        request,
        RegistryProblem(
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


@app.get("/v1/agents", response_model=list[AgentSummaryResponse])
async def list_agents_endpoint(
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(authenticated_identity)],
) -> list[dict[str, object]]:
    return await list_visible_agents(request.app.state.pool, identity)


@app.get("/v1/agents/{agent_id}/versions/{version}", response_model=ReleaseResponse)
async def get_release_endpoint(
    agent_id: str,
    version: str,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(authenticated_identity)],
) -> dict[str, object]:
    try:
        release = await get_visible_release(request.app.state.pool, identity, agent_id, version)
    except AccessError as error:
        raise _access_problem(error) from error
    return release.contract_response()


@app.post(
    "/v1/agents/{agent_id}/access-grants",
    response_model=AccessGrantResponse,
    status_code=201,
)
async def grant_access_endpoint(
    agent_id: str,
    body: GrantAccessRequest,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_admin)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    try:
        grant: AccessGrant = await grant_access(
            request.app.state.pool,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
            agent_id=agent_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            permission=body.permission,
        )
    except AccessError as error:
        raise _access_problem(error) from error
    return grant.contract_response()


@app.post("/v1/access-grants/{grant_id}:revoke", response_model=AccessGrantResponse)
async def revoke_access_endpoint(
    grant_id: UUID,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_admin)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    try:
        grant = await revoke_access(
            request.app.state.pool,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
            grant_id=grant_id,
        )
    except AccessError as error:
        raise _access_problem(error) from error
    return grant.contract_response()


@app.post("/v1/agents/{agent_id}/default-release", response_model=AgentSummaryResponse)
async def set_default_release_endpoint(
    agent_id: str,
    body: SetDefaultReleaseRequest,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_admin)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    try:
        return await set_default_release(
            request.app.state.pool,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
            agent_id=agent_id,
            release_id=body.release_id,
        )
    except LifecycleError as error:
        raise _lifecycle_problem(error) from error


@app.post("/v1/releases/{release_id}:deprecate", response_model=ReleaseResponse)
async def deprecate_release_endpoint(
    release_id: UUID,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_admin)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    try:
        release = await deprecate_release(
            request.app.state.pool,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
            release_id=release_id,
        )
    except LifecycleError as error:
        raise _lifecycle_problem(error) from error
    return release.contract_response()


@app.post(
    "/v1/run-specifications:resolve",
    response_model=SignedRunSpecificationResponse,
)
async def resolve_run_specification_endpoint(
    body: ResolveRunSpecificationRequest,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_resolver)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    signer: RunSpecificationSigner | None = getattr(request.app.state, "run_signer", None)
    if signer is None:
        raise RegistryProblem(
            503, "run_signing_not_configured", "Run-specification signing is not configured"
        )
    resolution_request = ResolutionRequest(**body.model_dump())
    try:
        specification = await resolve_run_specification(
            request.app.state.pool,
            signer,
            identity,
            resolution_request,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
        )
    except ResolutionError as error:
        raise _resolution_problem(error) from error
    return specification.contract_response()


@app.post("/v1/releases", response_model=ReleaseResponse, status_code=201)
async def publish_release_endpoint(
    body: PublishReleaseRequest,
    request: Request,
    identity: Annotated[ServiceIdentity, Depends(require_publisher)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ],
) -> dict[str, object]:
    try:
        validated = validate_publication(body.manifest, body.image, body.provenance)
    except PublicationValidationError as error:
        raise RegistryProblem(
            422,
            error.code,
            "Release publication evidence is invalid",
            details={"field": error.field},
        ) from error

    verifier: EvidenceVerifier | None = getattr(request.app.state, "evidence_verifier", None)
    if verifier is None:
        raise RegistryProblem(
            503, "publication_not_configured", "Publication security is not configured"
        )
    await verifier.verify(validated)
    try:
        release = await publish_release(
            request.app.state.pool,
            actor_id=identity.subject,
            idempotency_key=idempotency_key,
            manifest=body.manifest,
            image=body.image,
            provenance=body.provenance,
        )
    except PublicationError as error:
        raise _publication_problem(error) from error
    return release.contract_response()


def _publication_problem(error: PublicationError) -> RegistryProblem:
    problems = {
        "idempotency_conflict": (409, "The idempotency key was reused with different input"),
        "release_version_conflict": (409, "The agent version already exists"),
        "image_already_published": (409, "The OCI image is already published"),
        "agent_metadata_conflict": (409, "Agent metadata conflicts with its immutable identity"),
        "idempotency_key_invalid": (422, "The idempotency key is invalid"),
        "actor_invalid": (401, "The authenticated identity is invalid"),
        "idempotency_result_unavailable": (500, "The stored publication result is unavailable"),
    }
    status_code, title = problems.get(error.code, (500, "Release publication failed"))
    return RegistryProblem(status_code, error.code, title, retryable=status_code >= 500)


def _access_problem(error: AccessError) -> RegistryProblem:
    problems = {
        "release_not_found": (404, "Release not found"),
        "agent_not_found": (404, "Agent not found"),
        "grant_not_found": (404, "Access grant not found"),
        "grant_invalid": (422, "The access grant is invalid"),
        "idempotency_key_invalid": (422, "The idempotency key is invalid"),
        "idempotency_conflict": (409, "The idempotency key was reused with different input"),
        "idempotency_result_unavailable": (500, "The stored grant result is unavailable"),
    }
    status_code, title = problems.get(error.code, (500, "Access operation failed"))
    return RegistryProblem(status_code, error.code, title, retryable=status_code >= 500)


def _lifecycle_problem(error: LifecycleError) -> RegistryProblem:
    problems = {
        "agent_not_found": (404, "Agent not found"),
        "release_not_found": (404, "Release not found"),
        "release_deprecated": (409, "A deprecated release cannot become the default"),
        "default_release_deprecation_forbidden": (
            409,
            "The default release cannot be deprecated",
        ),
        "idempotency_key_invalid": (422, "The idempotency key is invalid"),
        "idempotency_conflict": (409, "The idempotency key was reused with different input"),
        "idempotency_result_unavailable": (500, "The stored lifecycle result is unavailable"),
    }
    status_code, title = problems.get(error.code, (500, "Release lifecycle operation failed"))
    return RegistryProblem(status_code, error.code, title, retryable=status_code >= 500)


def _resolution_problem(error: ResolutionError) -> RegistryProblem:
    problems = {
        "user_context_mismatch": (403, "The delegated user context does not match"),
        "release_not_found": (404, "Release not found"),
        "idempotency_key_invalid": (422, "The idempotency key is invalid"),
        "idempotency_conflict": (409, "The idempotency key was reused with different input"),
        "run_specification_conflict": (409, "The run already has a different specification"),
        "idempotency_result_unavailable": (500, "The stored specification is unavailable"),
        "stored_release_invalid": (500, "Stored release data is invalid"),
    }
    status_code, title = problems.get(error.code, (500, "Run specification resolution failed"))
    return RegistryProblem(status_code, error.code, title, retryable=status_code >= 500)
