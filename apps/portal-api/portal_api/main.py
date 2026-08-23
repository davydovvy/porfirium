import uuid
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from temporalio.client import Client

from .agent import ToolAgentWorkflowV2, workflow_id
from .auth import CurrentIdentity, Identity
from .chat import append_event, cancel_turn, event_stream, start_turn
from .config import settings
from .db import get_session
from .models import (
    Agent,
    AgentRunSnapshot,
    AgentToolGrant,
    AgentVersion,
    Conversation,
    Message,
    ModelAlias,
    ToolCatalogEntry,
    Turn,
    User,
    now_utc,
)

app = FastAPI(title="Porfirium Portal API", version="0.3.0")
Session = Annotated[AsyncSession, Depends(get_session)]


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    mode: Literal["direct", "agent"] = "direct"
    agent_version_id: uuid.UUID | None = None


class ConversationPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class TurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


async def ensure_user(identity: Identity, session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.keycloak_subject == identity.subject))
    if user is None:
        user = User(keycloak_subject=identity.subject)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def owned_conversation(
    conversation_id: uuid.UUID, user: User, session: AsyncSession
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.owner_id == user.id
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def conversation_json(item: Conversation) -> dict[str, object]:
    return {
        "id": str(item.id),
        "title": item.title,
        "mode": item.mode,
        "agent_version_id": str(item.agent_version_id) if item.agent_version_id else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def turn_json(item: Turn) -> dict[str, object]:
    return {
        "turn_id": str(item.id),
        "conversation_id": str(item.conversation_id),
        "mode": item.mode,
        "state": item.state,
        "correlation_id": item.correlation_id,
        "error_code": item.error_code,
        "agent_run_snapshot_id": (
            str(item.agent_run_snapshot_id) if item.agent_run_snapshot_id else None
        ),
        "events_url": f"/api/v1/turns/{item.id}/events",
    }


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(session: Session) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready"}


@app.get("/api/v1/config")
async def config() -> dict[str, str]:
    return {
        "oidc_issuer": settings.oidc_issuer,
        "oidc_client_id": "genai-demo-web",
        "api_audience": settings.oidc_audience,
    }


@app.get("/api/v1/me")
async def me(identity: CurrentIdentity, session: Session) -> dict[str, object]:
    user = await ensure_user(identity, session)
    return {
        "id": str(user.id),
        "username": identity.username,
        "display_name": identity.display_name,
        "email": identity.email,
        "roles": identity.roles,
        "capabilities": {"chat": True, "agent": True, "tools": True},
    }


@app.get("/api/v1/capabilities")
async def capabilities(identity: CurrentIdentity) -> dict[str, object]:
    return {
        "default_mode": "direct",
        "modes": [
            {"id": "direct", "name": "Direct LLM", "enabled": True},
            {"id": "agent", "name": "Agent", "enabled": True},
        ],
        "model": {"provider": "Yandex", "alias": "default"},
    }


def agent_version_json(agent: Agent, version: AgentVersion) -> dict[str, object]:
    return {
        "id": str(agent.id),
        "slug": agent.slug,
        "name": agent.name,
        "description": agent.description,
        "version": {
            "id": str(version.id),
            "version": version.version,
            "digest": version.digest,
            "status": version.status,
            "manifest": version.manifest,
            "published_at": version.published_at.isoformat(),
        },
    }


@app.get("/api/v1/agents")
async def agents(identity: CurrentIdentity, session: Session) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, Agent.default_version_id == AgentVersion.id)
            .where(AgentVersion.status == "published")
            .order_by(Agent.name)
        )
    ).all()
    return [agent_version_json(agent, version) for agent, version in rows]


@app.get("/api/v1/agents/{agent_slug}")
async def get_agent(
    agent_slug: str, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    row = (
        await session.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, Agent.default_version_id == AgentVersion.id)
            .where(Agent.slug == agent_slug, AgentVersion.status == "published")
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent_version_json(*row)


@app.get("/api/v1/agents/{agent_slug}/versions")
async def agent_versions(
    agent_slug: str, identity: CurrentIdentity, session: Session
) -> list[dict[str, object]]:
    agent = await session.scalar(select(Agent).where(Agent.slug == agent_slug))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    versions = (
        await session.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent.id, AgentVersion.status == "published")
            .order_by(AgentVersion.published_at.desc())
        )
    ).all()
    return [agent_version_json(agent, version)["version"] for version in versions]


@app.get("/api/v1/agents/{agent_slug}/versions/{version_number}")
async def get_agent_version(
    agent_slug: str, version_number: str, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    row = (
        await session.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .where(
                Agent.slug == agent_slug,
                AgentVersion.version == version_number,
                AgentVersion.status == "published",
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent version not found")
    return agent_version_json(*row)["version"]


@app.get("/api/v1/conversations")
async def conversations(identity: CurrentIdentity, session: Session) -> list[dict[str, object]]:
    user = await ensure_user(identity, session)
    items = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.owner_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
    ).all()
    return [conversation_json(item) for item in items]


@app.post("/api/v1/conversations", status_code=201)
async def create_conversation(
    body: ConversationCreate, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    user = await ensure_user(identity, session)
    agent_version_id = None
    if body.mode == "direct" and body.agent_version_id is not None:
        raise HTTPException(status_code=422, detail="Direct conversations cannot select an agent")
    if body.mode == "agent":
        if body.agent_version_id is None:
            agent_version_id = await session.scalar(
                select(Agent.default_version_id)
                .join(AgentVersion, Agent.default_version_id == AgentVersion.id)
                .where(AgentVersion.status == "published")
                .order_by(Agent.created_at)
                .limit(1)
            )
        else:
            agent_version_id = await session.scalar(
                select(AgentVersion.id).where(
                    AgentVersion.id == body.agent_version_id,
                    AgentVersion.status == "published",
                )
            )
        if agent_version_id is None:
            raise HTTPException(status_code=422, detail="Published agent version not found")
    item = Conversation(
        owner_id=user.id,
        title=body.title.strip(),
        mode=body.mode,
        agent_version_id=agent_version_id,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return conversation_json(item)


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    user = await ensure_user(identity, session)
    item = await session.scalar(
        select(Conversation)
        .options(selectinload(Conversation.messages), selectinload(Conversation.turns))
        .where(Conversation.id == conversation_id, Conversation.owner_id == user.id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = conversation_json(item)
    result["messages"] = [
        {
            "id": str(message.id),
            "turn_id": str(message.turn_id) if message.turn_id else None,
            "role": message.role,
            "content": message.content,
            "status": message.status,
            "created_at": message.created_at.isoformat(),
        }
        for message in sorted(item.messages, key=lambda value: value.created_at)
    ]
    active_turns = [turn for turn in item.turns if turn.state in {"accepted", "running"}]
    result["active_turn"] = (
        turn_json(max(active_turns, key=lambda value: value.created_at)) if active_turns else None
    )
    return result


@app.patch("/api/v1/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationPatch, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    user = await ensure_user(identity, session)
    item = await owned_conversation(conversation_id, user, session)
    item.title = body.title.strip()
    item.updated_at = now_utc()
    await session.commit()
    return conversation_json(item)


@app.post("/api/v1/conversations/{conversation_id}/turns", status_code=202)
async def create_turn(
    conversation_id: uuid.UUID, body: TurnCreate, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    user = await ensure_user(identity, session)
    conversation = await owned_conversation(conversation_id, user, session)
    existing = await session.scalar(
        select(Turn).where(Turn.owner_id == user.id, Turn.idempotency_key == body.idempotency_key)
    )
    if existing:
        return turn_json(existing)
    run_snapshot = None
    if conversation.mode == "agent":
        version = await session.get(AgentVersion, conversation.agent_version_id)
        if version is None or version.status != "published":
            raise HTTPException(status_code=409, detail="Conversation agent version is unavailable")
        model_alias = await session.get(ModelAlias, version.model_alias_id)
        granted_tools = (
            await session.scalars(
                select(ToolCatalogEntry)
                .join(AgentToolGrant, AgentToolGrant.tool_id == ToolCatalogEntry.id)
                .where(
                    AgentToolGrant.agent_version_id == version.id,
                    ToolCatalogEntry.enabled.is_(True),
                )
                .order_by(ToolCatalogEntry.stable_name)
            )
        ).all()
        run_snapshot = AgentRunSnapshot(
            agent_version_id=version.id,
            digest=version.digest,
            snapshot={
                "agent_version_id": str(version.id),
                "digest": version.digest,
                "manifest": version.manifest,
                "model": {
                    "alias": model_alias.alias,
                    "provider": model_alias.provider,
                    "model": model_alias.model,
                },
                "tools": [
                    {
                        "stable_name": tool.stable_name,
                        "schema_version": tool.schema_version,
                        "read_only": tool.read_only,
                    }
                    for tool in granted_tools
                ],
            },
        )
        session.add(run_snapshot)
        await session.flush()
    turn_id = uuid.uuid4()
    turn = Turn(
        id=turn_id,
        conversation_id=conversation.id,
        owner_id=user.id,
        idempotency_key=body.idempotency_key,
        mode=conversation.mode,
        state="accepted",
        correlation_id=turn_id.hex,
        workflow_id=workflow_id(turn_id) if conversation.mode == "agent" else None,
        agent_run_snapshot_id=run_snapshot.id if run_snapshot else None,
    )
    session.add(turn)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            turn_id=turn.id,
            role="user",
            content=body.content.strip(),
            status="complete",
        )
    )
    if conversation.title == "New conversation":
        conversation.title = body.content.strip()[:80]
    conversation.updated_at = now_utc()
    await session.commit()
    accepted_payload: dict[str, object] = {"mode": conversation.mode}
    if run_snapshot:
        accepted_payload.update(
            {
                "agent_version_id": str(run_snapshot.agent_version_id),
                "agent_digest": run_snapshot.digest,
                "agent_run_snapshot_id": str(run_snapshot.id),
            }
        )
    await append_event(turn.id, "turn.accepted", accepted_payload)
    if conversation.mode == "agent":
        try:
            temporal = await Client.connect(
                settings.temporal_address, namespace=settings.temporal_namespace
            )
            await temporal.start_workflow(
                ToolAgentWorkflowV2.run,
                str(turn.id),
                id=turn.workflow_id,
                task_queue=settings.temporal_task_queue,
            )
        except Exception as exc:
            turn.state = "failed"
            turn.error_code = "workflow_unavailable"
            turn.updated_at = now_utc()
            await session.commit()
            await append_event(
                turn.id,
                "turn.failed",
                {
                    "code": "workflow_unavailable",
                    "message": "The durable workflow service is unavailable.",
                    "correlation_id": turn.correlation_id,
                },
            )
            raise HTTPException(status_code=503, detail="Agent workflow unavailable") from exc
    else:
        start_turn(turn.id)
    return turn_json(turn)


async def owned_turn(turn_id: uuid.UUID, identity: Identity, session: AsyncSession) -> Turn:
    user = await ensure_user(identity, session)
    turn = await session.scalar(select(Turn).where(Turn.id == turn_id, Turn.owner_id == user.id))
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found")
    return turn


@app.get("/api/v1/turns/{turn_id}")
async def get_turn(
    turn_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    return turn_json(await owned_turn(turn_id, identity, session))


@app.get("/api/v1/turns/{turn_id}/events")
async def events(
    turn_id: uuid.UUID,
    identity: CurrentIdentity,
    session: Session,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    await owned_turn(turn_id, identity, session)
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    return StreamingResponse(
        event_stream(turn_id, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/turns/{turn_id}/cancel", status_code=202)
async def cancel(
    turn_id: uuid.UUID, identity: CurrentIdentity, session: Session
) -> dict[str, object]:
    turn = await owned_turn(turn_id, identity, session)
    if turn.state not in {"accepted", "running"}:
        return turn_json(turn)
    if turn.mode == "agent" and turn.workflow_id:
        temporal = await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
        await temporal.get_workflow_handle(turn.workflow_id).cancel()
        turn.state = "cancelled"
        turn.updated_at = now_utc()
        await session.commit()
        await append_event(turn.id, "turn.cancelled", {})
    elif not await cancel_turn(turn_id):
        turn.state = "cancelled"
        turn.updated_at = now_utc()
        await session.commit()
        await append_event(turn.id, "turn.cancelled", {})
    return turn_json(turn)
