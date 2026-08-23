import uuid

import pytest
from fastapi import HTTPException

from portal_api.auth import Identity
from portal_api.authoring import DraftFields, require_role, snapshot_contract
from portal_api.models import AgentDraftRevision, ModelAlias, ToolCatalogEntry
from portal_api.publisher import candidate_from_manifest


def identity(*roles: str) -> Identity:
    return Identity("subject", "author", "Author", None, roles)


def fields() -> DraftFields:
    return DraftFields(
        slug="portal-assistant",
        version="1.0.0",
        name="Portal Assistant",
        description="Portal-created declarative assistant",
        instructions="Answer clearly.",
        model_alias="default",
        tools=["demo_time-get_current_time"],
    )


def test_form_candidate_uses_shared_canonical_contract() -> None:
    manifest = fields().manifest()
    portal = candidate_from_manifest(manifest, source="portal:test:1")
    equivalent = candidate_from_manifest(dict(manifest), source="filesystem-equivalent")
    assert portal.artifact == equivalent.artifact
    assert portal.digest == equivalent.digest


def test_author_role_is_independent() -> None:
    require_role(identity("genai-agent-author"), "genai-agent-author")
    with pytest.raises(HTTPException) as error:
        require_role(identity("genai-user", "genai-admin"), "genai-agent-author")
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "role_required"


def test_draft_snapshot_is_pinned_to_revision_identity() -> None:
    manifest = fields().manifest()
    candidate = candidate_from_manifest(manifest)
    revision = AgentDraftRevision(
        id=uuid.uuid4(),
        draft_id=uuid.uuid4(),
        revision=1,
        manifest=manifest,
        content=candidate.artifact,
        digest=candidate.digest,
        author_id=uuid.uuid4(),
    )
    model = ModelAlias(alias="default", provider="yandex", model="test-model")
    tool = ToolCatalogEntry(
        stable_name="demo_time-get_current_time",
        server_name="demo-time",
        tool_name="get_current_time",
        schema_version="1",
        input_schema={"type": "object"},
        read_only=True,
        enabled=True,
    )
    snapshot = snapshot_contract(revision, model, [tool])
    assert snapshot["agent"]["version_id"] == str(revision.id)
    assert snapshot["agent"]["digest"] == candidate.digest
    assert snapshot["tools"][0]["policy_version"] == f"portal-test:{revision.id}"
