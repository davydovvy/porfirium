"""Increment 7 generic declarative agent runtime."""
# ruff: noqa: E501

import json

import sqlalchemy as sa
from alembic import op

from portal_api.catalog import manifest_digest

revision = "0007_generic_runtime"
down_revision = "0006_agent_immutable"
branch_labels = None
depends_on = None

VERSION_ID = "20000000-0000-0000-0000-000000000002"
PUBLICATION_ID = "50000000-0000-0000-0000-000000000002"
AGENT_ID = "10000000-0000-0000-0000-000000000001"
MANIFEST = {
    "schema_version": 2,
    "agent": {"id": "tool-assistant", "version": "1.1.0", "name": "Tool Assistant", "description": "Generic durable read-only time and MTG catalog assistant"},
    "runtime": {"kind": "declarative", "contract_version": 1},
    "model": {"alias": "default"},
    "instructions": "You are Porfirium's durable tool assistant. Use the available read-only time or MTG catalog tools when needed. Never invent tool results. Prices are static illustrative snapshots, not live quotes or purchasing advice. After tool results arrive, answer clearly and completely.",
    "tools": ["demo_time-get_current_time", "demo_time-convert_time", "demo_mtg_catalog-search_cards", "demo_mtg_catalog-get_card", "demo_mtg_catalog-compare_cards", "demo_mtg_catalog-list_sets"],
    "limits": {"max_iterations": 4, "max_tool_calls_per_step": 2, "max_tool_argument_bytes": 4096, "max_tool_result_bytes": 32768, "max_output_tokens": 2048},
}
DIGEST = manifest_digest(MANIFEST)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION reject_agent_run_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'agent run snapshots are immutable';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER agent_run_snapshots_immutable
        BEFORE UPDATE OR DELETE ON agent_run_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_agent_run_snapshot_mutation();
    """)
    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO agent_versions (id, agent_id, version, digest, manifest, model_alias_id, status, published_at) SELECT :id, :agent, '1.1.0', :digest, CAST(:manifest AS jsonb), id, 'draft', now() FROM model_aliases WHERE alias = 'default'"), {"id": VERSION_ID, "agent": AGENT_ID, "digest": DIGEST, "manifest": json.dumps(MANIFEST)})
    # Grants are copied, never mutated, from the reviewed historical release.
    bind.execute(sa.text("INSERT INTO agent_tool_grants (id, agent_version_id, tool_id, policy_version) SELECT gen_random_uuid(), :new_version, tool_id, 'tool-assistant-v1.1.0' FROM agent_tool_grants WHERE agent_version_id = '20000000-0000-0000-0000-000000000001'"), {"new_version": VERSION_ID})
    bind.execute(sa.text("UPDATE agent_versions SET status = 'published' WHERE id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("INSERT INTO agent_publications (id, agent_version_id, provenance, digest, validation, published_at) VALUES (:id, :version, 'bundled', :digest, CAST(:validation AS jsonb), now())"), {"id": PUBLICATION_ID, "version": VERSION_ID, "digest": DIGEST, "validation": json.dumps({"valid": True, "runtime_contract_version": 1})})
    # The selection upgrade is explicit and atomic; accepted snapshots are untouched.
    bind.execute(sa.text("UPDATE conversations SET agent_version_id = :new_version WHERE mode = 'agent' AND agent_version_id = '20000000-0000-0000-0000-000000000001'"), {"new_version": VERSION_ID})
    bind.execute(sa.text("UPDATE agents SET default_version_id = :new_version WHERE id = :agent"), {"new_version": VERSION_ID, "agent": AGENT_ID})


def downgrade() -> None:
    op.execute("UPDATE agents SET default_version_id = '20000000-0000-0000-0000-000000000001' WHERE id = '10000000-0000-0000-0000-000000000001'")
    op.execute("DROP TRIGGER agent_run_snapshots_immutable ON agent_run_snapshots")
    op.execute("DROP FUNCTION reject_agent_run_snapshot_mutation()")
