from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from temporalio.client import Client

from .agent import AgentRunWorkflow, workflow_id
from .auth import CurrentIdentity, Identity
from .chat import append_event
from .config import settings
from .db import get_session
from .models import (
    Agent,
    AgentDraft,
    AgentDraftRevision,
    AgentDraftTest,
    AgentLifecycleAudit,
    AgentPublication,
    AgentRunSnapshot,
    AgentVersion,
    Conversation,
    Message,
    ModelAlias,
    ToolCatalogEntry,
    Turn,
    User,
    now_utc,
)
from .publisher import (
    PublicationContext,
    PublicationError,
    candidate_from_manifest,
    platform_report,
    publish,
)
from .run_contracts import validate_run_snapshot

router = APIRouter(prefix="/api/v1")
Session = Annotated[AsyncSession, Depends(get_session)]
AUTHOR_ROLE = "genai-agent-author"
PUBLISHER_ROLE = "genai-agent-publisher"


class Limits(BaseModel):
    max_iterations: int = Field(default=4, ge=1, le=16)
    max_tool_calls_per_step: int = Field(default=2, ge=1, le=8)
    max_tool_argument_bytes: int = Field(default=4096, ge=256, le=65536)
    max_tool_result_bytes: int = Field(default=32768, ge=1024, le=1048576)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)


class DraftFields(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=20_000)
    model_alias: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    tools: list[str] = Field(default_factory=list, max_length=32)
    limits: Limits = Field(default_factory=Limits)

    def manifest(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "agent": {
                "id": self.slug,
                "version": self.version,
                "name": self.name.strip(),
                "description": self.description.strip(),
            },
            "runtime": {"kind": "declarative", "contract_version": 1},
            "model": {"alias": self.model_alias},
            "instructions": self.instructions.strip(),
            "tools": self.tools,
            "limits": self.limits.model_dump(),
        }


class DraftPatch(DraftFields):
    expected_revision: int = Field(ge=1)


class TestTurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def require_role(identity: Identity, role: str) -> None:
    if role not in identity.roles:
        raise HTTPException(status_code=403, detail={"code": "role_required", "role": role})


async def user_for(identity: Identity, session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.keycloak_subject == identity.subject))
    if user is None:
        user = User(keycloak_subject=identity.subject)
        session.add(user)
        await session.flush()
    return user


async def owned_draft(
    draft_id: uuid.UUID, identity: Identity, session: AsyncSession, *, publisher: bool = False
) -> tuple[AgentDraft, User]:
    user = await user_for(identity, session)
    query = select(AgentDraft).where(AgentDraft.id == draft_id)
    if not publisher:
        query = query.where(AgentDraft.author_id == user.id)
    draft = await session.scalar(query)
    if draft is None:
        raise HTTPException(status_code=404, detail={"code": "draft_not_found"})
    return draft, user


def draft_json(draft: AgentDraft) -> dict[str, object]:
    return {
        "id": str(draft.id),
        "state": draft.state,
        "current_revision": draft.current_revision,
        "manifest": draft.manifest,
        "validation": draft.validation,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def revision_json(revision: AgentDraftRevision) -> dict[str, object]:
    return {
        "id": str(revision.id),
        "draft_id": str(revision.draft_id),
        "revision": revision.revision,
        "manifest": revision.manifest,
        "digest": revision.digest,
        "created_at": revision.created_at.isoformat(),
    }


async def exact_revision(
    draft: AgentDraft, number: int, session: AsyncSession
) -> AgentDraftRevision:
    revision = await session.scalar(
        select(AgentDraftRevision).where(
            AgentDraftRevision.draft_id == draft.id, AgentDraftRevision.revision == number
        )
    )
    if revision is None:
        raise HTTPException(status_code=404, detail={"code": "draft_revision_not_found"})
    return revision


def publication_http_error(error: PublicationError) -> HTTPException:
    status = 409 if error.code.endswith("conflict") else 422
    if error.code == "platform_resolution_failed":
        status = 503
    return HTTPException(
        status_code=status,
        detail={"code": error.code, "message": error.detail or error.code},
    )


@router.get("/agent-authoring/options")
async def authoring_options(identity: CurrentIdentity, session: Session) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    models = list(
        (
            await session.scalars(
                select(ModelAlias).where(ModelAlias.enabled.is_(True)).order_by(ModelAlias.alias)
            )
        ).all()
    )
    tools = list(
        (
            await session.scalars(
                select(ToolCatalogEntry)
                .where(ToolCatalogEntry.enabled.is_(True), ToolCatalogEntry.read_only.is_(True))
                .order_by(ToolCatalogEntry.stable_name, ToolCatalogEntry.schema_version)
            )
        ).all()
    )
    counts: dict[str, int] = {}
    for tool in tools:
        counts[tool.stable_name] = counts.get(tool.stable_name, 0) + 1
    return {
        "models": [{"alias": model.alias} for model in models],
        "tools": [
            {"stable_name": tool.stable_name, "schema_version": tool.schema_version}
            for tool in tools
            if counts[tool.stable_name] == 1
        ],
    }


@router.get("/agent-drafts")
async def drafts(identity: CurrentIdentity, session: Session) -> list[dict[str, object]]:
    require_role(identity, AUTHOR_ROLE)
    user = await user_for(identity, session)
    items = list(
        (
            await session.scalars(
                select(AgentDraft)
                .where(AgentDraft.author_id == user.id)
                .order_by(AgentDraft.updated_at.desc())
            )
        ).all()
    )
    return [draft_json(item) for item in items]


async def insert_revision(
    session: AsyncSession, draft: AgentDraft, user: User, fields: DraftFields, number: int
) -> AgentDraftRevision:
    try:
        candidate = candidate_from_manifest(fields.manifest(), source=f"portal:{draft.id}:{number}")
    except PublicationError as error:
        raise publication_http_error(error) from error
    revision = AgentDraftRevision(
        draft_id=draft.id,
        revision=number,
        manifest=candidate.manifest,
        content=candidate.artifact,
        digest=candidate.digest,
        author_id=user.id,
    )
    session.add(revision)
    draft.manifest = candidate.manifest
    draft.current_revision = number
    draft.state = "editing"
    draft.validation = None
    draft.updated_at = now_utc()
    return revision


@router.post("/agent-drafts", status_code=201)
async def create_draft(
    body: DraftFields, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    user = await user_for(identity, session)
    draft = AgentDraft(author_id=user.id, manifest={}, state="editing", current_revision=0)
    session.add(draft)
    await session.flush()
    revision = await insert_revision(session, draft, user, body, 1)
    await session.commit()
    return {**draft_json(draft), "revision": revision_json(revision)}


@router.get("/agent-drafts/{draft_id}")
async def get_draft(
    draft_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    draft, _ = await owned_draft(draft_id, identity, session)
    revision = await exact_revision(draft, draft.current_revision, session)
    return {**draft_json(draft), "revision": revision_json(revision)}


@router.get("/agent-publication-queue")
async def publication_queue(
    identity: CurrentIdentity, session: Session
) -> list[dict[str, object]]:
    require_role(identity, PUBLISHER_ROLE)
    items = list(
        (
            await session.scalars(
                select(AgentDraft)
                .where(AgentDraft.state.in_(("validated", "published")))
                .order_by(AgentDraft.updated_at.desc())
            )
        ).all()
    )
    return [draft_json(item) for item in items]


@router.get("/agent-drafts/{draft_id}/review")
async def review_draft(
    draft_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, PUBLISHER_ROLE)
    draft, _ = await owned_draft(draft_id, identity, session, publisher=True)
    revision = await exact_revision(draft, draft.current_revision, session)
    tested = await session.scalar(
        select(Turn.id)
        .join(AgentDraftTest, AgentDraftTest.conversation_id == Turn.conversation_id)
        .where(AgentDraftTest.draft_revision_id == revision.id, Turn.state == "completed")
        .limit(1)
    )
    return {
        **draft_json(draft),
        "revision": revision_json(revision),
        "successfully_tested": tested is not None,
    }


@router.patch("/agent-drafts/{draft_id}")
async def update_draft(
    draft_id: uuid.UUID, body: DraftPatch, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    draft, user = await owned_draft(draft_id, identity, session)
    if draft.state == "published":
        raise HTTPException(status_code=409, detail={"code": "draft_sealed"})
    if body.expected_revision != draft.current_revision:
        raise HTTPException(status_code=409, detail={"code": "draft_revision_conflict"})
    revision = await insert_revision(session, draft, user, body, draft.current_revision + 1)
    await session.commit()
    return {**draft_json(draft), "revision": revision_json(revision)}


@router.post("/agent-drafts/{draft_id}/revisions/{number}/validate")
async def validate_draft(
    draft_id: uuid.UUID, number: int, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    draft, _ = await owned_draft(draft_id, identity, session)
    if number != draft.current_revision:
        raise HTTPException(status_code=409, detail={"code": "draft_revision_conflict"})
    revision = await exact_revision(draft, number, session)
    candidate = candidate_from_manifest(revision.manifest, source=f"portal:{draft.id}:{number}")
    try:
        report, _, _ = await platform_report(session, candidate)
    except PublicationError as error:
        raise publication_http_error(error) from error
    draft.validation = {**report, "revision": number}
    draft.state = "validated"
    draft.updated_at = now_utc()
    await session.commit()
    return draft.validation


def snapshot_contract(
    revision: AgentDraftRevision,
    model: ModelAlias,
    tools: list[ToolCatalogEntry],
) -> dict[str, object]:
    manifest = revision.manifest
    model_name = settings.llm_model if model.model == "configured-at-runtime" else model.model
    if not model_name:
        raise HTTPException(status_code=503, detail={"code": "agent_model_unresolved"})
    by_name = {tool.stable_name: tool for tool in tools}
    declared = [str(name) for name in manifest["tools"]]  # type: ignore[index]
    contract: dict[str, object] = {
        "contract_version": 1,
        "agent": {
            "id": manifest["agent"]["id"],  # type: ignore[index]
            "version": manifest["agent"]["version"],  # type: ignore[index]
            "version_id": str(revision.id),
            "digest": revision.digest,
        },
        "runtime": manifest["runtime"],
        "instructions": manifest["instructions"],
        "model": {"alias": model.alias, "provider": model.provider, "model": model_name},
        "tools": [
            {
                "stable_name": name,
                "server_name": by_name[name].server_name,
                "tool_name": by_name[name].tool_name,
                "schema_version": by_name[name].schema_version,
                "read_only": True,
                "definition": by_name[name].input_schema,
                "policy_version": f"portal-test:{revision.id}",
            }
            for name in declared
        ],
        "limits": manifest["limits"],
    }
    validate_run_snapshot(contract)
    return contract


@router.post("/agent-drafts/{draft_id}/revisions/{number}/tests", status_code=201)
async def create_draft_test(
    draft_id: uuid.UUID, number: int, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    draft, user = await owned_draft(draft_id, identity, session)
    if (
        number != draft.current_revision
        or not draft.validation
        or draft.validation.get("revision") != number
    ):
        raise HTTPException(status_code=409, detail={"code": "draft_not_validated"})
    revision = await exact_revision(draft, number, session)
    candidate = candidate_from_manifest(revision.manifest, source=f"portal:{draft.id}:{number}")
    try:
        _, model, tools = await platform_report(session, candidate)
    except PublicationError as error:
        raise publication_http_error(error) from error
    conversation = Conversation(
        owner_id=user.id,
        title=f"Draft test · {candidate.agent_id}:{candidate.version}",
        mode="agent-test",
    )
    session.add(conversation)
    await session.flush()
    test = AgentDraftTest(
        draft_revision_id=revision.id,
        owner_id=user.id,
        conversation_id=conversation.id,
        digest=revision.digest,
    )
    session.add(test)
    await session.flush()
    snapshot = AgentRunSnapshot(
        draft_revision_id=revision.id,
        digest=revision.digest,
        snapshot=snapshot_contract(revision, model, tools),
    )
    session.add(snapshot)
    await session.flush()
    await session.commit()
    return {
        "id": str(test.id),
        "revision": number,
        "digest": test.digest,
        "conversation_id": str(conversation.id),
        "run_snapshot_id": str(snapshot.id),
    }


async def owned_test(
    test_id: uuid.UUID, identity: Identity, session: AsyncSession
) -> tuple[AgentDraftTest, User]:
    user = await user_for(identity, session)
    test = await session.scalar(
        select(AgentDraftTest).where(
            AgentDraftTest.id == test_id, AgentDraftTest.owner_id == user.id
        )
    )
    if test is None:
        raise HTTPException(status_code=404, detail={"code": "draft_test_not_found"})
    return test, user


@router.get("/agent-draft-tests/{test_id}")
async def get_draft_test(
    test_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    test, _ = await owned_test(test_id, identity, session)
    turns = list(
        (
            await session.scalars(
                select(Turn)
                .where(Turn.conversation_id == test.conversation_id)
                .order_by(Turn.created_at)
            )
        ).all()
    )
    return {
        "id": str(test.id),
        "draft_revision_id": str(test.draft_revision_id),
        "digest": test.digest,
        "turns": [{"id": str(turn.id), "state": turn.state} for turn in turns],
    }


@router.post("/agent-draft-tests/{test_id}/turns", status_code=202)
async def create_test_turn(
    test_id: uuid.UUID, body: TestTurnCreate, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, AUTHOR_ROLE)
    test, user = await owned_test(test_id, identity, session)
    existing = await session.scalar(
        select(Turn).where(Turn.owner_id == user.id, Turn.idempotency_key == body.idempotency_key)
    )
    if existing:
        return {
            "turn_id": str(existing.id),
            "state": existing.state,
            "events_url": f"/api/v1/turns/{existing.id}/events",
        }
    prior_turn = await session.scalar(
        select(Turn.id).where(Turn.conversation_id == test.conversation_id).limit(1)
    )
    if prior_turn is not None:
        raise HTTPException(status_code=409, detail={"code": "draft_test_already_run"})
    active = await session.scalar(
        select(func.count())
        .select_from(Turn)
        .where(
            Turn.conversation_id == test.conversation_id, Turn.state.in_(("accepted", "running"))
        )
    )
    if active:
        raise HTTPException(status_code=409, detail={"code": "test_turn_active"})
    snapshot = await session.scalar(
        select(AgentRunSnapshot).where(AgentRunSnapshot.draft_revision_id == test.draft_revision_id)
    )
    if snapshot is None:
        raise HTTPException(status_code=409, detail={"code": "draft_test_snapshot_missing"})
    turn_id = uuid.uuid4()
    turn = Turn(
        id=turn_id,
        conversation_id=test.conversation_id,
        owner_id=user.id,
        idempotency_key=body.idempotency_key,
        mode="agent",
        state="accepted",
        correlation_id=turn_id.hex,
        workflow_id=workflow_id(turn_id),
        agent_run_snapshot_id=snapshot.id,
    )
    session.add(turn)
    session.add(
        Message(
            conversation_id=test.conversation_id,
            turn_id=turn.id,
            role="user",
            content=body.content.strip(),
            status="complete",
        )
    )
    await session.commit()
    await append_event(turn.id, "turn.accepted", {"mode": "agent-test"})
    try:
        temporal = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        await temporal.start_workflow(
            AgentRunWorkflow.run,
            {"turn_id": str(turn.id), "run_snapshot_id": str(snapshot.id)},
            id=turn.workflow_id,
            task_queue=settings.temporal_agent_run_task_queue,
        )
    except Exception:
        turn.state = "failed"
        turn.error_code = "workflow_start_failed"
        await session.commit()
        await append_event(
            turn.id,
            "turn.failed",
            {
                "code": "workflow_start_failed",
                "message": "The draft test could not be started.",
            },
        )
    return {
        "turn_id": str(turn.id),
        "state": turn.state,
        "events_url": f"/api/v1/turns/{turn.id}/events",
    }


@router.post("/agent-drafts/{draft_id}/revisions/{number}/publish")
async def publish_draft(
    draft_id: uuid.UUID, number: int, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, PUBLISHER_ROLE)
    draft, publisher = await owned_draft(draft_id, identity, session, publisher=True)
    if number != draft.current_revision:
        raise HTTPException(status_code=409, detail={"code": "draft_revision_conflict"})
    revision = await exact_revision(draft, number, session)
    successful_test = await session.scalar(
        select(Turn.id)
        .join(AgentDraftTest, AgentDraftTest.conversation_id == Turn.conversation_id)
        .where(AgentDraftTest.draft_revision_id == revision.id, Turn.state == "completed")
        .limit(1)
    )
    if successful_test is None:
        raise HTTPException(status_code=409, detail={"code": "draft_test_required"})
    candidate = candidate_from_manifest(revision.manifest, source=f"portal:{draft.id}:{number}")
    try:
        result = await publish(
            session,
            candidate,
            PublicationContext("portal", publisher.id, draft.id, number),
        )
        release = await session.get(AgentVersion, uuid.UUID(str(result["release_id"])))
        assert release is not None
        draft.agent_id = release.agent_id
        draft.state = "published"
        draft.updated_at = now_utc()
        await session.commit()
    except PublicationError as error:
        await session.rollback()
        raise publication_http_error(error) from error
    return result


@router.get("/agent-publications/{publication_id}")
async def get_publication(
    publication_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    require_role(identity, PUBLISHER_ROLE)
    publication = await session.get(AgentPublication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail={"code": "publication_not_found"})
    return {
        "id": str(publication.id),
        "agent_version_id": str(publication.agent_version_id),
        "draft_id": str(publication.draft_id) if publication.draft_id else None,
        "publisher_id": str(publication.publisher_id) if publication.publisher_id else None,
        "provenance": publication.provenance,
        "digest": publication.digest,
        "validation": publication.validation,
        "published_at": publication.published_at.isoformat(),
    }


@router.post("/agents/{agent_slug}/versions/{version}/deprecate")
async def deprecate_release(
    agent_slug: str,
    version: str,
    identity: CurrentIdentity,
    session: Session,
) -> dict[str, object]:
    require_role(identity, PUBLISHER_ROLE)
    row = (
        await session.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .where(Agent.slug == agent_slug, AgentVersion.version == version)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "release_not_found"})
    agent, release = row
    if release.status == "deprecated":
        return {"agent_id": agent.slug, "version": release.version, "status": release.status}
    if release.status != "published":
        raise HTTPException(status_code=409, detail={"code": "release_not_published"})
    if agent.default_version_id == release.id:
        raise HTTPException(
            status_code=409, detail={"code": "default_release_deprecation_forbidden"}
        )
    actor = await user_for(identity, session)
    release.status = "deprecated"
    session.add(
        AgentLifecycleAudit(
            agent_version_id=release.id,
            actor_id=actor.id,
            action="deprecate",
            previous_status="published",
            new_status="deprecated",
        )
    )
    await session.commit()
    return {"agent_id": agent.slug, "version": release.version, "status": release.status}
