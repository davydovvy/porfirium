import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keycloak_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="owner")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("owner_id", "id", name="uq_conversation_owner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    mode: Mapped[str] = mapped_column(String(32), default="direct")
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_versions.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    owner: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")
    turns: Mapped[list["Turn"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("turns.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="complete", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_turn_owner_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id"), index=True, nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="direct", nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    workflow_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    agent_run_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_run_snapshots.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    conversation: Mapped[Conversation] = relationship(back_populates="turns")
    events: Mapped[list["TurnEvent"]] = relationship(back_populates="turn")
    tool_requests: Mapped[list["ToolRequest"]] = relationship(back_populates="turn")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    default_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", use_alter=True, name="fk_agents_default_version")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ModelAlias(Base):
    __tablename__ = "model_aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alias: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_version_number"),
        UniqueConstraint("agent_id", "digest", name="uq_agent_version_digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    digest: Mapped[str] = mapped_column(String(71), unique=True, nullable=False)
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model_alias_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_aliases.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AgentDraft(Base):
    __tablename__ = "agent_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    validation: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AgentPublication(Base):
    __tablename__ = "agent_publications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_drafts.id"))
    publisher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    digest: Mapped[str] = mapped_column(String(71), nullable=False)
    validation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ToolCatalogEntry(Base):
    __tablename__ = "tool_catalog"
    __table_args__ = (
        UniqueConstraint("stable_name", "schema_version", name="uq_tool_catalog_stable_schema"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stable_name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AgentToolGrant(Base):
    __tablename__ = "agent_tool_grants"
    __table_args__ = (
        UniqueConstraint("agent_version_id", "tool_id", name="uq_agent_version_tool_grant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tool_catalog.id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)


class AgentRunSnapshot(Base):
    __tablename__ = "agent_run_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), index=True)
    digest: Mapped[str] = mapped_column(String(71), nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TurnEvent(Base):
    __tablename__ = "turn_events"
    __table_args__ = (UniqueConstraint("turn_id", "sequence", name="uq_turn_event_sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("turns.id"), index=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    turn: Mapped[Turn] = relationship(back_populates="events")


class ToolRequest(Base):
    __tablename__ = "tool_requests"
    __table_args__ = (
        UniqueConstraint("turn_id", "tool_call_id", name="uq_tool_request_turn_call"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("turns.id"), index=True, nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    server_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    external_tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn: Mapped[Turn] = relationship(back_populates="tool_requests")
