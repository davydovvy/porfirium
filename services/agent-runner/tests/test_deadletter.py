import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from agent_runner.deadletter import dead_letter, delivery_attempt, event_identity, replay


class Pool:
    def __init__(self) -> None:
        self.executions: list[tuple[object, ...]] = []

    async def execute(self, query: str, *arguments: object) -> str:
        self.executions.append(arguments)
        return "INSERT 0 1"


class JetStream:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object], dict[str, str]]] = []

    async def publish(self, subject: str, payload: bytes, headers: dict[str, str]) -> None:
        self.published.append((subject, json.loads(payload), headers))


def test_delivery_attempt_defaults_and_reads_jetstream_metadata() -> None:
    assert delivery_attempt(SimpleNamespace()) == 1
    assert delivery_attempt(SimpleNamespace(metadata=SimpleNamespace(num_delivered=5))) == 5


def test_malformed_identity_is_deterministic_and_safe() -> None:
    first = event_identity(b"not-json", None)
    second = event_identity(b"not-json", {"id": "secret", "type": "bad"})
    assert first == second
    assert first[1] == "porfirium.unknown.v1"


def test_dead_letter_persists_encrypted_original_and_publishes_bounded_diagnostic(
    monkeypatch,
) -> None:
    event_id = "0646af1f-e305-4ec0-a47e-cff026f41a42"
    message = SimpleNamespace(
        data=json.dumps({"id": event_id, "type": "porfirium.run.command.requested.v1"}).encode(),
        subject="porfirium.run.command.requested",
        metadata=SimpleNamespace(num_delivered=5),
    )
    pool = Pool()
    jetstream = JetStream()
    monkeypatch.setenv("RUNNER_DLQ_ENCRYPTION_KEY", Fernet.generate_key().decode())
    result = asyncio.run(
        dead_letter(
            pool, jetstream, message, consumer="consumer", error=ValueError("private"),
            envelope=json.loads(message.data),
        )
    )
    assert isinstance(result, UUID)
    assert pool.executions[0][1] == UUID(event_id)
    assert event_id.encode() not in pool.executions[0][7]
    subject, diagnostic, headers = jetstream.published[0]
    assert subject == "porfirium.dlq.message"
    assert diagnostic["data"]["attempts"] == 5
    assert diagnostic["data"]["error_code"] == "valueerror"
    assert "private" not in json.dumps(diagnostic)
    assert headers["Nats-Msg-Id"] == str(result)


def test_malformed_payload_cannot_be_replayed(monkeypatch) -> None:
    key = Fernet.generate_key()
    monkeypatch.setenv("RUNNER_DLQ_ENCRYPTION_KEY", key.decode())

    class Connection:
        async def fetchrow(self, query: str, dead_letter_id: UUID) -> dict[str, object]:
            payload = json.dumps({"malformed_sha256": "a" * 64}).encode()
            return {
                "replayed_at": None,
                "original_payload_ciphertext": Fernet(key).encrypt(payload),
            }

        def transaction(self) -> "Connection":
            return self

        async def __aenter__(self) -> "Connection":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class ReplayPool:
        def acquire(self) -> Connection:
            return Connection()

    with pytest.raises(ValueError, match="cannot be replayed"):
        asyncio.run(replay(ReplayPool(), JetStream(), UUID(int=1), "operator"))
