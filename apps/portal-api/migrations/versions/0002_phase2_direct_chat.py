"""Phase 2 direct chat persistence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_phase2"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_turn_owner_idempotency"),
    )
    op.create_index("ix_turns_conversation_id", "turns", ["conversation_id"])
    op.create_index("ix_turns_owner_id", "turns", ["owner_id"])
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("turns.id")),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_turn_id", "messages", ["turn_id"])
    op.create_table(
        "turn_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("turns.id"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("turn_id", "sequence", name="uq_turn_event_sequence"),
    )
    op.create_index("ix_turn_events_turn_id", "turn_events", ["turn_id"])


def downgrade() -> None:
    op.drop_table("turn_events")
    op.drop_table("messages")
    op.drop_table("turns")
