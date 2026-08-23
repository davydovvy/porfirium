import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from portal_api import authoring
from portal_api.auth import Identity
from portal_api.authoring import (
    DraftFields,
    create_test_turn,
    require_role,
    snapshot_contract,
)
from portal_api.authoring import (
    TestTurnCreate as DraftTestTurnCreate,
)
from portal_api.models import (
    AgentDraftRevision,
    AgentDraftTest,
    AgentRunSnapshot,
    Message,
    ModelAlias,
    ToolCatalogEntry,
    Turn,
    User,
)
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


@pytest.mark.asyncio
async def test_draft_test_flushes_turn_before_adding_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(id=uuid.uuid4(), keycloak_subject="subject")
    draft_test = AgentDraftTest(
        id=uuid.uuid4(),
        draft_revision_id=uuid.uuid4(),
        owner_id=user.id,
        conversation_id=uuid.uuid4(),
        digest="sha256:test",
    )
    snapshot = AgentRunSnapshot(
        id=uuid.uuid4(),
        draft_revision_id=draft_test.draft_revision_id,
        digest=draft_test.digest,
        snapshot={},
    )

    class Session:
        def __init__(self) -> None:
            self.flushed = False
            self.scalars = iter((None, None, 0, snapshot))

        async def scalar(self, _statement: object) -> object:
            return next(self.scalars)

        def add(self, value: object) -> None:
            if isinstance(value, Message):
                assert self.flushed, "the turn must exist before its message is inserted"
            assert isinstance(value, Turn | Message)

        async def flush(self) -> None:
            self.flushed = True

        async def commit(self) -> None:
            pass

    temporal = AsyncMock()
    monkeypatch.setattr(authoring, "owned_test", AsyncMock(return_value=(draft_test, user)))
    monkeypatch.setattr(authoring, "append_event", AsyncMock())
    monkeypatch.setattr(authoring.Client, "connect", AsyncMock(return_value=temporal))

    result = await create_test_turn(
        draft_test.id,
        DraftTestTurnCreate(content="What time is it?", idempotency_key="test-key"),
        identity("genai-agent-author"),
        Session(),  # type: ignore[arg-type]
    )

    assert result["state"] == "accepted"
    temporal.start_workflow.assert_awaited_once()
