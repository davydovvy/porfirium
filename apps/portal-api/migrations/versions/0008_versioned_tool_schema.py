"""Version the corrected MTG search contract and publish tool-assistant 1.2.0."""
# ruff: noqa: E501

import json

import sqlalchemy as sa
from alembic import op

from portal_api.catalog import manifest_digest

revision = "0008_versioned_tool_schema"
down_revision = "0007_generic_runtime"
branch_labels = None
depends_on = None

AGENT_ID = "10000000-0000-0000-0000-000000000001"
VERSION_ID = "20000000-0000-0000-0000-000000000003"
PREVIOUS_VERSION_ID = "20000000-0000-0000-0000-000000000002"
TOOL_ID = "40000000-0000-0000-0000-000000000007"
PUBLICATION_ID = "50000000-0000-0000-0000-000000000003"
SEARCH_TOOL = "demo_mtg_catalog-search_cards"
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "maxLength": 200, "default": ""},
        "set_code": {"type": ["string", "null"], "maxLength": 8},
        "colors": {"type": ["array", "null"], "items": {"type": "string", "enum": ["W", "U", "B", "R", "G"]}, "maxItems": 5, "uniqueItems": True},
        "card_type": {"type": ["string", "null"], "maxLength": 64},
        "rarity": {"type": ["string", "null"], "enum": ["common", "uncommon", "rare", "mythic", None]},
        "min_price": {"type": ["string", "null"], "maxLength": 16},
        "max_price": {"type": ["string", "null"], "maxLength": 16},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": [],
    "additionalProperties": False,
}
MANIFEST = {
    "schema_version": 2,
    "agent": {"id": "tool-assistant", "version": "1.2.0", "name": "Tool Assistant", "description": "Generic durable read-only time and MTG catalog assistant"},
    "runtime": {"kind": "declarative", "contract_version": 1},
    "model": {"alias": "default"},
    "instructions": "You are Porfirium's durable tool assistant. Use the available read-only time or MTG catalog tools when needed. For MTG set listings, filter with set_code and omit query unless the user also asks for text matching. Never invent tool results. Prices are static illustrative snapshots, not live quotes or purchasing advice. After tool results arrive, answer clearly and completely.",
    "tools": ["demo_time-get_current_time", "demo_time-convert_time", SEARCH_TOOL, "demo_mtg_catalog-get_card", "demo_mtg_catalog-compare_cards", "demo_mtg_catalog-list_sets"],
    "limits": {"max_iterations": 4, "max_tool_calls_per_step": 2, "max_tool_argument_bytes": 4096, "max_tool_result_bytes": 32768, "max_output_tokens": 2048},
}
DIGEST = manifest_digest(MANIFEST)


def upgrade() -> None:
    op.drop_constraint("tool_catalog_stable_name_key", "tool_catalog", type_="unique")
    op.create_unique_constraint(
        "uq_tool_catalog_stable_schema", "tool_catalog", ["stable_name", "schema_version"]
    )
    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO tool_catalog (id, stable_name, server_name, tool_name, schema_version, input_schema, read_only, enabled) VALUES (:id, :stable, 'demo_mtg_catalog', 'search_cards', '1.1.0', CAST(:schema AS jsonb), true, true)"), {"id": TOOL_ID, "stable": SEARCH_TOOL, "schema": json.dumps(SEARCH_SCHEMA)})
    bind.execute(sa.text("INSERT INTO agent_versions (id, agent_id, version, digest, manifest, model_alias_id, status, published_at) SELECT :id, :agent, '1.2.0', :digest, CAST(:manifest AS jsonb), id, 'draft', now() FROM model_aliases WHERE alias = 'default'"), {"id": VERSION_ID, "agent": AGENT_ID, "digest": DIGEST, "manifest": json.dumps(MANIFEST)})
    bind.execute(sa.text("INSERT INTO agent_tool_grants (id, agent_version_id, tool_id, policy_version) SELECT gen_random_uuid(), :new_version, g.tool_id, 'tool-assistant-v1.2.0' FROM agent_tool_grants g JOIN tool_catalog t ON t.id = g.tool_id WHERE g.agent_version_id = :old_version AND t.stable_name <> :search_tool"), {"new_version": VERSION_ID, "old_version": PREVIOUS_VERSION_ID, "search_tool": SEARCH_TOOL})
    bind.execute(sa.text("INSERT INTO agent_tool_grants (id, agent_version_id, tool_id, policy_version) VALUES (gen_random_uuid(), :version, :tool, 'tool-assistant-v1.2.0')"), {"version": VERSION_ID, "tool": TOOL_ID})
    bind.execute(sa.text("UPDATE agent_versions SET status = 'published' WHERE id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("INSERT INTO agent_publications (id, agent_version_id, provenance, digest, validation, published_at) VALUES (:id, :version, 'bundled', :digest, CAST(:validation AS jsonb), now())"), {"id": PUBLICATION_ID, "version": VERSION_ID, "digest": DIGEST, "validation": json.dumps({"valid": True, "runtime_contract_version": 1, "tool_schema_version": "1.1.0"})})
    bind.execute(sa.text("UPDATE agents SET default_version_id = :version WHERE id = :agent"), {"version": VERSION_ID, "agent": AGENT_ID})


def downgrade() -> None:
    bind = op.get_bind()
    snapshots = bind.scalar(sa.text("SELECT count(*) FROM agent_run_snapshots WHERE agent_version_id = :version"), {"version": VERSION_ID})
    if snapshots:
        raise RuntimeError("cannot remove tool-assistant:1.2.0 after immutable snapshots exist")
    bind.execute(sa.text("UPDATE agents SET default_version_id = :previous WHERE id = :agent"), {"previous": PREVIOUS_VERSION_ID, "agent": AGENT_ID})
    bind.execute(sa.text("UPDATE conversations SET agent_version_id = :previous WHERE agent_version_id = :version"), {"previous": PREVIOUS_VERSION_ID, "version": VERSION_ID})
    bind.execute(sa.text("UPDATE agent_versions SET status = 'draft' WHERE id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("DELETE FROM agent_tool_grants WHERE agent_version_id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("DELETE FROM agent_publications WHERE agent_version_id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("DELETE FROM agent_versions WHERE id = :version"), {"version": VERSION_ID})
    bind.execute(sa.text("DELETE FROM tool_catalog WHERE id = :tool"), {"tool": TOOL_ID})
    op.drop_constraint("uq_tool_catalog_stable_schema", "tool_catalog", type_="unique")
    op.create_unique_constraint("tool_catalog_stable_name_key", "tool_catalog", ["stable_name"])
