"""Store immutable canonical artifacts for filesystem publication."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_filesystem_publication"
down_revision = "0008_versioned_tool_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("digest", sa.String(71), nullable=False, unique=True),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes = octet_length(content)", name="ck_agent_artifact_size"),
        sa.CheckConstraint("size_bytes <= 32768", name="ck_agent_artifact_bound"),
    )
    op.add_column("agent_versions", sa.Column("artifact_id", postgresql.UUID(as_uuid=True)))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, manifest FROM agent_versions")).mappings()
    for row in rows:
        content = json.dumps(
            row["manifest"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
        artifact_id = bind.scalar(
            sa.text(
                "INSERT INTO agent_artifacts "
                "(id, digest, media_type, content, size_bytes, created_at) "
                "VALUES (gen_random_uuid(), :digest, 'application/vnd.porfirium.agent+json', "
                ":content, :size, now()) ON CONFLICT (digest) DO UPDATE SET "
                "digest = EXCLUDED.digest "
                "RETURNING id"
            ),
            {"digest": digest, "content": content, "size": len(content)},
        )
        bind.execute(
            sa.text("UPDATE agent_versions SET artifact_id = :artifact WHERE id = :version"),
            {"artifact": artifact_id, "version": row["id"]},
        )
    op.alter_column("agent_versions", "artifact_id", nullable=False)
    op.create_foreign_key(
        "fk_agent_versions_artifact", "agent_versions", "agent_artifacts", ["artifact_id"], ["id"]
    )
    op.execute(
        """
        CREATE FUNCTION reject_agent_artifact_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'agent artifacts are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_artifacts_immutable
        BEFORE UPDATE OR DELETE ON agent_artifacts
        FOR EACH ROW EXECUTE FUNCTION reject_agent_artifact_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_agent_version_artifact() RETURNS trigger AS $$
        DECLARE artifact_digest text;
        BEGIN
          SELECT digest INTO artifact_digest FROM agent_artifacts WHERE id = NEW.artifact_id;
          IF artifact_digest IS NULL OR artifact_digest IS DISTINCT FROM NEW.digest THEN
            RAISE EXCEPTION 'agent version artifact digest mismatch';
        END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_version_artifact_matches
        BEFORE INSERT OR UPDATE OF artifact_id, digest ON agent_versions
        FOR EACH ROW EXECUTE FUNCTION validate_agent_version_artifact()
        """
    )


def downgrade() -> None:
    raise RuntimeError("immutable agent artifacts make downgrade unsupported after Increment 8")
