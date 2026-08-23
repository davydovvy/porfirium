"""Increment 6 versioned agent catalog and immutable run snapshots."""
# ruff: noqa: E501

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_agent_catalog"
down_revision = "0004_phase4"
branch_labels = None
depends_on = None

AGENT_ID = "10000000-0000-0000-0000-000000000001"
VERSION_ID = "20000000-0000-0000-0000-000000000001"
MODEL_ALIAS_ID = "30000000-0000-0000-0000-000000000001"
PUBLICATION_ID = "50000000-0000-0000-0000-000000000001"
DIGEST = "sha256:e67130e726d431e143d53c56244b18cad043683ab29273bee0112529d2317ec2"
TOOL_NAMES = (
    "demo_time-get_current_time",
    "demo_time-convert_time",
    "demo_mtg_catalog-search_cards",
    "demo_mtg_catalog-get_card",
    "demo_mtg_catalog-compare_cards",
    "demo_mtg_catalog-list_sets",
)
MANIFEST = {
    "schema_version": 1,
    "agent": {"id": "tool-assistant", "version": "1.0.0", "name": "Tool Assistant", "description": "Durable read-only time and MTG catalog assistant"},
    "runtime": {"kind": "temporal", "workflow": "PorfiriumToolAgentWorkflowV2"},
    "model": {"alias": "default"},
    "instructions": "You are Porfirium's durable tool assistant. Use the available read-only time or MTG catalog tools when they are needed. Never invent tool results. Prices are static illustrative snapshots, not live quotes or purchasing advice. After tool results arrive, answer clearly and completely.",
    "tools": list(TOOL_NAMES),
    "limits": {"max_iterations": 4, "max_tool_calls_per_step": 2, "max_tool_argument_bytes": 4096, "max_tool_result_bytes": 32768},
}


def upgrade() -> None:
    op.create_table(
        "model_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("alias", sa.String(63), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("default_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("digest", sa.String(71), nullable=False, unique=True),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("model_alias_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_aliases.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_version_number"),
        sa.UniqueConstraint("agent_id", "digest", name="uq_agent_version_digest"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_foreign_key(
        "fk_agents_default_version",
        "agents",
        "agent_versions",
        ["default_version_id"],
        ["id"],
    )
    op.create_table(
        "agent_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id")),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("validation", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_drafts_agent_id", "agent_drafts", ["agent_id"])
    op.create_index("ix_agent_drafts_author_id", "agent_drafts", ["author_id"])
    op.create_table(
        "agent_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_drafts.id")),
        sa.Column("publisher_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("digest", sa.String(71), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_publications_agent_version_id", "agent_publications", ["agent_version_id"])
    op.create_table(
        "tool_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("stable_name", sa.String(255), nullable=False, unique=True),
        sa.Column("server_name", sa.String(128), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "agent_tool_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tool_catalog.id"), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.UniqueConstraint("agent_version_id", "tool_id", name="uq_agent_version_tool_grant"),
    )
    op.create_index("ix_agent_tool_grants_agent_version_id", "agent_tool_grants", ["agent_version_id"])
    op.create_index("ix_agent_tool_grants_tool_id", "agent_tool_grants", ["tool_id"])
    op.create_table(
        "agent_run_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("digest", sa.String(71), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_run_snapshots_agent_version_id", "agent_run_snapshots", ["agent_version_id"])
    op.add_column("conversations", sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_versions.id")))
    op.create_index("ix_conversations_agent_version_id", "conversations", ["agent_version_id"])
    op.add_column("turns", sa.Column("agent_run_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_run_snapshots.id")))
    op.create_unique_constraint("uq_turns_agent_run_snapshot_id", "turns", ["agent_run_snapshot_id"])

    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO model_aliases (id, alias, provider, model, enabled, created_at) VALUES (:id, 'default', 'yandex', 'configured-at-runtime', true, now())"), {"id": MODEL_ALIAS_ID})
    bind.execute(sa.text("INSERT INTO agents (id, slug, name, description, created_at) VALUES (:id, 'tool-assistant', 'Tool Assistant', 'Durable read-only time and MTG catalog assistant', now())"), {"id": AGENT_ID})
    bind.execute(sa.text("INSERT INTO agent_versions (id, agent_id, version, digest, manifest, model_alias_id, status, published_at) VALUES (:id, :agent, '1.0.0', :digest, CAST(:manifest AS jsonb), :model, 'published', now())"), {"id": VERSION_ID, "agent": AGENT_ID, "digest": DIGEST, "manifest": json.dumps(MANIFEST), "model": MODEL_ALIAS_ID})
    bind.execute(sa.text("UPDATE agents SET default_version_id = :version WHERE id = :agent"), {"version": VERSION_ID, "agent": AGENT_ID})
    bind.execute(
        sa.text("INSERT INTO agent_publications (id, agent_version_id, provenance, digest, validation, published_at) VALUES (:id, :version, 'bundled', :digest, CAST(:validation AS jsonb), now())"),
        {
            "id": PUBLICATION_ID,
            "version": VERSION_ID,
            "digest": DIGEST,
            "validation": json.dumps({"valid": True}),
        },
    )
    from portal_api.tool_policy import TOOLS
    for index, stable_name in enumerate(TOOL_NAMES, start=1):
        policy = TOOLS[stable_name]
        tool_id = f"40000000-0000-0000-0000-{index:012d}"
        grant_id = f"60000000-0000-0000-0000-{index:012d}"
        bind.execute(sa.text("INSERT INTO tool_catalog (id, stable_name, server_name, tool_name, schema_version, input_schema, read_only, enabled) VALUES (:id, :stable, :server, :tool, :schema, CAST(:input AS jsonb), true, true)"), {"id": tool_id, "stable": stable_name, "server": policy.server_name, "tool": policy.tool_name, "schema": policy.schema_version, "input": json.dumps(policy.arguments_schema)})
        bind.execute(sa.text("INSERT INTO agent_tool_grants (id, agent_version_id, tool_id, policy_version) VALUES (:id, :version, :tool, 'tool-assistant-v1.0.0')"), {"id": grant_id, "version": VERSION_ID, "tool": tool_id})
    bind.execute(sa.text("UPDATE conversations SET agent_version_id = :version WHERE mode = 'agent'"), {"version": VERSION_ID})


def downgrade() -> None:
    op.drop_constraint("uq_turns_agent_run_snapshot_id", "turns", type_="unique")
    op.drop_column("turns", "agent_run_snapshot_id")
    op.drop_index("ix_conversations_agent_version_id", table_name="conversations")
    op.drop_column("conversations", "agent_version_id")
    op.drop_table("agent_run_snapshots")
    op.drop_table("agent_tool_grants")
    op.drop_table("tool_catalog")
    op.drop_table("agent_publications")
    op.drop_table("agent_drafts")
    op.drop_constraint("fk_agents_default_version", "agents", type_="foreignkey")
    op.drop_table("agent_versions")
    op.drop_table("agents")
    op.drop_table("model_aliases")
