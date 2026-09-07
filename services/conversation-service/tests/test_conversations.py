from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from conversation_service.domain import MemoryStore
from conversation_service.main import app, sse
from conversation_service.problems import ConversationProblem

OWNER = UUID("10000000-0000-0000-0000-000000000001")
OTHER = UUID("10000000-0000-0000-0000-000000000002")


@pytest.fixture
def client() -> TestClient:
    app.state.store = MemoryStore()
    return TestClient(app)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def headers(owner: UUID = OWNER, key: str | None = None) -> dict[str, str]:
    result = {"X-User-ID": str(owner)}
    if key:
        result["Idempotency-Key"] = key
    return result


def create_conversation(client: TestClient) -> dict:
    response = client.post(
        "/v1/conversations",
        headers=headers(key="conversation-1"),
        json={"title": "Demo", "release_id": str(uuid4()), "thread_id": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()


def envelope(conversation: dict, event_type: str, data: dict, **overrides: object) -> dict:
    event_id = uuid4()
    trace_id = "1" * 32
    value = {
        "specversion": "1.0",
        "id": str(event_id),
        "type": event_type,
        "source": "agent-runtime-api",
        "subject": f"conversation/{conversation['conversation_id']}",
        "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "user_id": str(OWNER),
        "conversation_id": conversation["conversation_id"],
        "thread_id": conversation["thread_id"],
        "run_id": str(overrides.pop("run_id", uuid4())),
        "correlation_id": str(UUID(hex=trace_id)),
        "causation_id": str(uuid4()),
        "traceparent": f"00-{trace_id}-{'2' * 16}-01",
        "schema_version": 1,
        "data": data,
    }
    value.update(overrides)
    return value


@pytest.mark.anyio
async def test_projection_rejects_missing_mismatched_and_oversized_trace_context() -> None:
    store = MemoryStore()
    conversation = await store.create_conversation(
        OWNER,
        "trace-conversation",
        {"title": "Trace", "release_id": uuid4(), "thread_id": uuid4(),
         "configuration_revision_id": None},
    )
    base = envelope(
        {"conversation_id": str(conversation.conversation_id),
         "thread_id": str(conversation.thread_id)},
        "porfirium.message.started.v1",
        {"message_id": str(uuid4())},
    )
    missing = dict(base)
    missing.pop("traceparent")
    with pytest.raises(ConversationProblem, match="event_invalid"):
        await store.project(missing)

    mismatch = dict(base)
    mismatch["correlation_id"] = str(uuid4())
    with pytest.raises(ConversationProblem, match="event_invalid"):
        await store.project(mismatch)

    oversized = dict(base)
    oversized["data"] = {"message_id": str(uuid4()), "content": "x" * (1024 * 1024)}
    with pytest.raises(ConversationProblem, match="event_invalid"):
        await store.project(oversized)


def test_create_and_message_are_idempotent_and_atomic(client: TestClient) -> None:
    conversation = create_conversation(client)
    duplicate = client.post(
        "/v1/conversations",
        headers=headers(key="conversation-1"),
        json={
            "title": "Demo",
            "release_id": conversation["release_id"],
            "thread_id": conversation["thread_id"],
        },
    )
    assert duplicate.json()["conversation_id"] == conversation["conversation_id"]

    body = {
        "message_id": str(uuid4()),
        "run_id": str(uuid4()),
        "content": "hello",
        "delegation_grant_id": str(uuid4()),
    }
    first = client.post(
        f"/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(key="message-key-1"),
        json=body,
    )
    second = client.post(
        f"/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(key="message-key-1"),
        json=body,
    )
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(app.state.store.outbox) == 1
    assert app.state.store.outbox[0]["run_input"] == {
        "trigger_type": "user_message",
        "trigger_id": body["message_id"],
        "value": "hello",
    }
    assert first.json()["conversation_sequence"] == 1

    conflict = client.post(
        f"/v1/conversations/{conversation['conversation_id']}/messages",
        headers=headers(key="message-key-1"),
        json={**body, "content": "different"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_owner_cannot_discover_or_mutate_foreign_conversation(client: TestClient) -> None:
    conversation = create_conversation(client)
    conversation_id = conversation["conversation_id"]
    assert (
        client.get(f"/v1/conversations/{conversation_id}", headers=headers(OTHER)).status_code
        == 404
    )
    assert client.get("/v1/conversations", headers=headers(OTHER)).json() == []
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=headers(OTHER, "foreign-message"),
        json={
            "message_id": str(uuid4()),
            "run_id": str(uuid4()),
            "content": "x",
            "delegation_grant_id": str(uuid4()),
        },
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_runtime_projection_deduplicates_and_keeps_canonical_completion() -> None:
    store = MemoryStore()
    conversation = await store.create_conversation(
        OWNER,
        "conversation-1",
        {
            "title": "Demo",
            "release_id": uuid4(),
            "thread_id": uuid4(),
            "configuration_revision_id": None,
        },
    )
    conversation_json = {
        "conversation_id": str(conversation.conversation_id),
        "thread_id": str(conversation.thread_id),
    }
    run_id, message_id = uuid4(), uuid4()
    started = envelope(
        conversation_json,
        "porfirium.message.started.v1",
        {"message_id": str(message_id)},
        run_id=run_id,
    )
    assert await store.project(started) == 1
    assert await store.project(started) is None
    await store.project(
        envelope(
            conversation_json,
            "porfirium.message.delta.v1",
            {"message_id": str(message_id), "chunk_sequence": 1, "content": "hel"},
            run_id=run_id,
        )
    )
    await store.project(
        envelope(
            conversation_json,
            "porfirium.message.delta.v1",
            {"message_id": str(message_id), "chunk_sequence": 2, "content": "lo"},
            run_id=run_id,
        )
    )
    content = "hello"
    await store.project(
        envelope(
            conversation_json,
            "porfirium.message.completed.v1",
            {
                "message_id": str(message_id),
                "content": content,
                "chunk_count": 2,
                "content_bytes": len(content.encode()),
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "finish_reason": "stop",
                "usage": {},
            },
            run_id=run_id,
        )
    )
    store.chunks.pop(message_id)  # simulate short-lived delta expiry
    projection = await store.projection(OWNER, conversation.conversation_id)
    assert projection["messages"][0].content == "hello"
    assert projection["messages"][0].status == "completed"


@pytest.mark.anyio
async def test_invalid_completion_does_not_become_terminal() -> None:
    store = MemoryStore()
    conversation = await store.create_conversation(
        OWNER,
        "conversation-1",
        {
            "title": "Demo",
            "release_id": uuid4(),
            "thread_id": uuid4(),
            "configuration_revision_id": None,
        },
    )
    view = {
        "conversation_id": str(conversation.conversation_id),
        "thread_id": str(conversation.thread_id),
    }
    run_id, message_id = uuid4(), uuid4()
    await store.project(
        envelope(
            view, "porfirium.message.started.v1", {"message_id": str(message_id)}, run_id=run_id
        )
    )
    await store.project(
        envelope(
            view,
            "porfirium.message.delta.v1",
            {"message_id": str(message_id), "chunk_sequence": 1, "content": "hello"},
            run_id=run_id,
        )
    )
    with pytest.raises(ConversationProblem, match="Canonical content hash"):
        await store.project(
            envelope(
                view,
                "porfirium.message.completed.v1",
                {
                    "message_id": str(message_id),
                    "content": "hello",
                    "chunk_count": 1,
                    "content_bytes": 5,
                    "content_sha256": "0" * 64,
                },
                run_id=run_id,
            )
        )
    assert store.messages[message_id].status == "streaming"


@pytest.mark.anyio
async def test_replay_after_sequence_has_no_gap() -> None:
    store = MemoryStore()
    conversation = await store.create_conversation(
        OWNER,
        "conversation-1",
        {
            "title": "Demo",
            "release_id": uuid4(),
            "thread_id": uuid4(),
            "configuration_revision_id": None,
        },
    )
    for index in range(3):
        await store.create_message(
            OWNER,
            conversation.conversation_id,
            f"message-{index}",
            {
                "message_id": uuid4(),
                "run_id": uuid4(),
                "content": str(index),
                "delegation_grant_id": uuid4(),
            },
        )
    replay = await store.replay(OWNER, conversation.conversation_id, 1)
    assert [item.sequence for item in replay] == [2, 3]
    assert sse(replay[0]).startswith("id: 2\nevent: message.completed\n")


@pytest.mark.anyio
@pytest.mark.parametrize("commit_first", [False, True])
async def test_input_saga_is_hidden_until_commit_and_order_independent(
    commit_first: bool,
) -> None:
    store = MemoryStore()
    conversation = await store.create_conversation(
        OWNER, "conversation-saga",
        {"title": "Demo", "release_id": uuid4(), "thread_id": uuid4(),
         "configuration_revision_id": None},
    )
    grant_id, run_id, suspension_id, checkpoint_id = uuid4(), uuid4(), uuid4(), uuid4()
    await store.create_message(
        OWNER, conversation.conversation_id, "saga-message",
        {"message_id": uuid4(), "run_id": run_id, "content": "start",
         "delegation_grant_id": grant_id},
    )
    request_id = uuid5(NAMESPACE_URL, f"porfirium:suspension:{suspension_id}")
    view = {
        "conversation_id": str(conversation.conversation_id),
        "thread_id": str(conversation.thread_id),
    }
    proposed = envelope(
        view, "porfirium.input.request_proposed.v1",
        {"suspension_id": str(suspension_id), "checkpoint_id": str(checkpoint_id),
         "prompt": "Approve?", "response_schema": {"type": "boolean"}}, run_id=run_id,
    )
    committed = envelope(
        view, "porfirium.run.suspension_committed.v1",
        {"run_id": str(run_id), "suspension_id": str(suspension_id),
         "checkpoint_id": str(checkpoint_id), "input_request_id": str(request_id)}, run_id=run_id,
    )
    first, second = (committed, proposed) if commit_first else (proposed, committed)
    assert await store.project(first) is None
    assert not [event for event in store.events[conversation.conversation_id]
                if event.event_type == "input.request_created"]
    assert await store.project(second) is not None
    assert store.inputs[request_id].state == "pending"

    response_run_id = uuid4()
    result = await store.answer_input(OWNER, request_id, "response-key", response_run_id, True)
    assert await store.answer_input(
        OWNER, request_id, "response-key", response_run_id, True
    ) == result
    with pytest.raises(ConversationProblem, match="already answered"):
        await store.answer_input(OWNER, request_id, "another-key", uuid4(), False)
