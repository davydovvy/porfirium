"""Phase 4 durable tool request audit records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_phase4"
down_revision = "0003_phase3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "turn_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("turns.id"), nullable=False
        ),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("model_call_id", sa.String(255), nullable=False),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("agent_version", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("server_name", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("external_tool_name", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("decision_reason", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("turn_id", "tool_call_id", name="uq_tool_request_turn_call"),
    )
    op.create_index("ix_tool_requests_turn_id", "tool_requests", ["turn_id"])
    op.create_index("ix_tool_requests_owner_id", "tool_requests", ["owner_id"])


def downgrade() -> None:
    op.drop_table("tool_requests")
