from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

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
    value = {
        "id": str(uuid4()),
        "type": event_type,
        "user_id": str(OWNER),
        "conversation_id": conversation["conversation_id"],
        "run_id": str(overrides.pop("run_id", uuid4())),
        "schema_version": 1,
        "data": data,
    }
    value.update(overrides)
    return value


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
    conversation_json = {"conversation_id": str(conversation.conversation_id)}
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
    view = {"conversation_id": str(conversation.conversation_id)}
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
