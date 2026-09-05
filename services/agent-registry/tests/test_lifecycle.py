from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import uuid4

import pytest

from agent_registry.lifecycle import LifecycleError, deprecate_release, set_default_release


class AsyncContext(AbstractAsyncContextManager[Any]):
    def __init__(self, value: Any) -> None:
        self.value = value

    async def __aenter__(self) -> Any:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


class Connection:
    def __init__(self, rows: Iterable[object]) -> None:
        self.rows = iter(rows)
        self.statements: list[str] = []

    def transaction(self) -> AsyncContext:
        return AsyncContext(self)

    async def execute(self, query: str, *args: object) -> str:
        self.statements.append(query)
        return "OK"

    async def fetchrow(self, query: str, *args: object) -> object:
        self.statements.append(query)
        return next(self.rows)


class Pool:
    def __init__(self, rows: Iterable[object]) -> None:
        self.connection = Connection(rows)

    def acquire(self) -> AsyncContext:
        return AsyncContext(self.connection)

    async def fetch(self, query: str, *args: object) -> object:
        raise AssertionError("not used")

    async def fetchrow(self, query: str, *args: object) -> object:
        raise AssertionError("not used")


def test_selects_published_release_as_default_with_audit() -> None:
    release_id = uuid4()
    pool = Pool(
        [
            None,
            {
                "agent_id": "example-agent",
                "name": "Example",
                "description": "Example agent",
                "default_release_id": None,
            },
            {"agent_id": "example-agent", "status": "published"},
        ]
    )

    result = asyncio.run(
        set_default_release(
            pool,
            actor_id="administrator",
            idempotency_key="default-0001",
            agent_id="example-agent",
            release_id=release_id,
        )
    )

    statements = "\n".join(pool.connection.statements)
    assert result["default_release_id"] == str(release_id)
    assert "UPDATE agents SET default_release_id" in statements
    assert "default_release_changed" in statements


def test_default_replay_returns_original_response_snapshot() -> None:
    release_id = uuid4()
    response = {
        "agent_id": "example-agent",
        "name": "Example",
        "description": "Example agent",
        "default_release_id": str(release_id),
    }
    from agent_registry.domain import request_sha256

    digest = request_sha256({"agent_id": "example-agent", "release_id": str(release_id)})
    pool = Pool([{"request_sha256": digest, "response_body": json.dumps(response)}])

    replay = asyncio.run(
        set_default_release(
            pool,
            actor_id="administrator",
            idempotency_key="default-0002",
            agent_id="example-agent",
            release_id=release_id,
        )
    )

    assert replay == response
    assert not any("UPDATE agents" in statement for statement in pool.connection.statements)


def test_cannot_deprecate_current_default() -> None:
    release_id = uuid4()
    pool = Pool(
        [
            None,
            {"agent_id": "example-agent"},
            {"default_release_id": release_id},
            {
                "release_id": release_id,
                "agent_id": "example-agent",
                "version": "1.0.0",
                "image": "registry.local/example@sha256:" + "a" * 64,
                "manifest": {},
                "status": "published",
            },
        ]
    )

    with pytest.raises(LifecycleError, match="default_release_deprecation_forbidden"):
        asyncio.run(
            deprecate_release(
                pool,
                actor_id="administrator",
                idempotency_key="deprecate-0001",
                release_id=release_id,
            )
        )

    assert not any("UPDATE releases" in statement for statement in pool.connection.statements)


def test_deprecates_former_default_once() -> None:
    release_id = uuid4()
    replacement_id = uuid4()
    published = {
        "release_id": release_id,
        "agent_id": "example-agent",
        "version": "1.0.0",
        "image": "registry.local/example@sha256:" + "a" * 64,
        "manifest": {},
        "status": "published",
    }
    pool = Pool(
        [
            None,
            {"agent_id": "example-agent"},
            {"default_release_id": replacement_id},
            published,
            {**published, "status": "deprecated"},
        ]
    )

    release = asyncio.run(
        deprecate_release(
            pool,
            actor_id="administrator",
            idempotency_key="deprecate-0002",
            release_id=release_id,
        )
    )

    statements = "\n".join(pool.connection.statements)
    assert release.status == "deprecated"
    assert statements.count("INSERT INTO publication_audit") == 1
