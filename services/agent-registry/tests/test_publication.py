from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest

from agent_registry.publication import PublicationError, publish_release

DIGEST = "sha256:" + "a" * 64
IMAGE = f"registry.local/example-agent@{DIGEST}"
MANIFEST: dict[str, object] = {
    "apiVersion": "porfirium.ai/v1",
    "kind": "Agent",
    "metadata": {"name": "example-agent", "version": "1.0.0"},
    "spec": {
        "image": IMAGE,
        "entrypoint": "example_agent.main:graph",
        "sdk": ">=1.0,<2.0",
        "models": ["default"],
        "tools": [],
        "configSchema": {},
        "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
    },
}
PROVENANCE = {
    "subjectDigest": DIGEST,
    "signature": "c2lnbmF0dXJl",
    "keyId": "test-key",
}


class AsyncContext(AbstractAsyncContextManager[Any]):
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeConnection:
    def __init__(self, rows: Iterable[object]) -> None:
        self.rows = iter(rows)
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> AsyncContext:
        return AsyncContext(self)

    async def execute(self, query: str, *args: object) -> str:
        self.executions.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args: object) -> object:
        self.executions.append((query, args))
        return next(self.rows)


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> AsyncContext:
        return AsyncContext(self.connection)


def test_publication_is_one_transaction_with_audit_and_idempotency() -> None:
    connection = FakeConnection([None, None, None])

    release = asyncio.run(
        publish_release(
            FakePool(connection),
            actor_id="publisher-service",
            idempotency_key="publish-0001",
            manifest=MANIFEST,
            image=IMAGE,
            provenance=PROVENANCE,
        )
    )

    statements = "\n".join(query for query, _ in connection.executions)
    assert release.agent_id == "example-agent"
    assert "INSERT INTO agents" in statements
    assert "INSERT INTO releases" in statements
    assert "INSERT INTO publication_audit" in statements
    assert "INSERT INTO idempotency_records" in statements


def test_exact_idempotent_replay_returns_original_release() -> None:
    first_connection = FakeConnection([None, None, None])
    first = asyncio.run(
        publish_release(
            FakePool(first_connection),
            actor_id="publisher-service",
            idempotency_key="publish-0002",
            manifest=MANIFEST,
            image=IMAGE,
            provenance=PROVENANCE,
        )
    )
    idempotency_insert = next(
        args
        for query, args in first_connection.executions
        if "INSERT INTO idempotency_records" in query
    )
    request_digest = idempotency_insert[2]
    replay_connection = FakeConnection(
        [
            {
                "request_sha256": request_digest,
                "release_id": first.release_id,
                "agent_id": first.agent_id,
                "version": first.version,
                "image": first.image,
                "manifest": first.manifest,
                "status": first.status,
            }
        ]
    )

    replay = asyncio.run(
        publish_release(
            FakePool(replay_connection),
            actor_id="publisher-service",
            idempotency_key="publish-0002",
            manifest=MANIFEST,
            image=IMAGE,
            provenance=PROVENANCE,
        )
    )

    assert replay == first
    assert not any("INSERT INTO releases" in query for query, _ in replay_connection.executions)


def test_idempotency_key_reuse_with_different_request_is_rejected() -> None:
    connection = FakeConnection(
        [
            {
                "request_sha256": "0" * 64,
                "release_id": None,
                "agent_id": None,
                "version": None,
                "image": None,
                "manifest": None,
                "status": None,
            }
        ]
    )

    with pytest.raises(PublicationError, match="idempotency_conflict"):
        asyncio.run(
            publish_release(
                FakePool(connection),
                actor_id="publisher-service",
                idempotency_key="publish-0003",
                manifest=MANIFEST,
                image=IMAGE,
                provenance=PROVENANCE,
            )
        )
