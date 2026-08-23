"""Add immutable portal drafts and private draft-test snapshot sources."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_portal_builder"
down_revision = "0009_filesystem_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_drafts",
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "agent_draft_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_drafts.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("digest", sa.String(71), nullable=False),
        sa.Column(
            "author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("validation", postgresql.JSONB()),
        sa.Column("tested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("octet_length(content) <= 32768", name="ck_agent_draft_revision_bound"),
        sa.UniqueConstraint("draft_id", "revision", name="uq_agent_draft_revision"),
    )
    op.create_index("ix_agent_draft_revisions_draft_id", "agent_draft_revisions", ["draft_id"])
    op.create_index("ix_agent_draft_revisions_author_id", "agent_draft_revisions", ["author_id"])
    op.alter_column("agent_run_snapshots", "agent_version_id", nullable=True)
    op.add_column(
        "agent_run_snapshots",
        sa.Column(
            "draft_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_draft_revisions.id"),
        ),
    )
    op.create_index(
        "ix_agent_run_snapshots_draft_revision_id", "agent_run_snapshots", ["draft_revision_id"]
    )
    op.create_check_constraint(
        "ck_agent_run_snapshot_one_source",
        "agent_run_snapshots",
        "(agent_version_id IS NOT NULL) <> (draft_revision_id IS NOT NULL)",
    )
    op.create_table(
        "agent_draft_tests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_draft_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("digest", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_draft_tests_draft_revision_id", "agent_draft_tests", ["draft_revision_id"]
    )
    op.create_index("ix_agent_draft_tests_owner_id", "agent_draft_tests", ["owner_id"])
    op.create_table(
        "agent_lifecycle_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("new_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_lifecycle_audits_agent_version_id", "agent_lifecycle_audits", ["agent_version_id"]
    )
    op.create_index("ix_agent_lifecycle_audits_actor_id", "agent_lifecycle_audits", ["actor_id"])
    op.execute(
        """
        CREATE FUNCTION reject_agent_draft_revision_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'agent draft revisions are immutable'; END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_draft_revisions_immutable
        BEFORE UPDATE OR DELETE ON agent_draft_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_agent_draft_revision_mutation()
        """
    )


def downgrade() -> None:
    raise RuntimeError("immutable portal publication evidence makes downgrade unsupported")
