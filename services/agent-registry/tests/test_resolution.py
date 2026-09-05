from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_registry.auth import ServiceIdentity
from agent_registry.domain import canonical_json, request_sha256
from agent_registry.resolution import (
    ResolutionError,
    ResolutionRequest,
    RunSpecificationSigner,
    resolve_run_specification,
)

DIGEST = "a" * 64


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
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> AsyncContext:
        return AsyncContext(self)

    async def execute(self, query: str, *args: object) -> str:
        self.executions.append((query, args))
        return "OK"

    async def fetchrow(self, query: str, *args: object) -> object:
        self.executions.append((query, args))
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


def request_and_identity() -> tuple[ResolutionRequest, ServiceIdentity]:
    user_id = uuid4()
    request = ResolutionRequest(
        run_id=uuid4(),
        user_id=user_id,
        conversation_id=uuid4(),
        thread_id=uuid4(),
        release_id=uuid4(),
        delegation_grant_id=uuid4(),
        trace_id="b" * 32,
    )
    identity = ServiceIdentity(
        "runner-service",
        "agent-runner",
        frozenset({"genai-agent-run-resolver", "agent-user"}),
        frozenset({"engineering"}),
        str(user_id),
    )
    return request, identity


def published_release(request: ResolutionRequest) -> dict[str, object]:
    return {
        "release_id": request.release_id,
        "agent_id": "example-agent",
        "version": "1.2.3",
        "image": "registry.local/example-agent@sha256:" + "c" * 64,
        "manifest_sha256": DIGEST,
        "status": "published",
        "manifest": {
            "spec": {
                "entrypoint": "example.main:graph",
                "sdk": ">=1.0,<2.0",
                "models": ["default"],
                "tools": ["time.current"],
                "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
            }
        },
    }


def test_resolves_stored_release_into_verifiable_immutable_payload() -> None:
    request, identity = request_and_identity()
    pool = Pool([None, None, published_release(request)])
    private_key = Ed25519PrivateKey.generate()
    signer = RunSpecificationSigner(private_key, "registry-run-key")

    result = asyncio.run(
        resolve_run_specification(
            pool,
            signer,
            identity,
            request,
            actor_id=identity.subject,
            idempotency_key="resolve-0001",
        )
    )

    private_key.public_key().verify(result.signature, canonical_json(result.payload))
    assert result.payload["release"]["image"] == published_release(request)["image"]  # type: ignore[index]
    assert result.payload["requested_tools"] == ["time.current"]
    statements = "\n".join(query for query, _ in pool.connection.executions)
    assert "g.permission IN ('run', 'admin')" in statements
    assert "INSERT INTO run_specifications" in statements


def test_rejects_caller_supplied_user_different_from_delegated_context() -> None:
    request, identity = request_and_identity()
    mismatched = ServiceIdentity(
        identity.subject, identity.client_id, identity.roles, identity.groups, str(uuid4())
    )

    with pytest.raises(ResolutionError, match="user_context_mismatch"):
        asyncio.run(
            resolve_run_specification(
                Pool([]),
                RunSpecificationSigner(Ed25519PrivateKey.generate(), "key"),
                mismatched,
                request,
                actor_id=identity.subject,
                idempotency_key="resolve-0002",
            )
        )


def test_rejects_unauthorized_or_deprecated_release_as_not_found() -> None:
    request, identity = request_and_identity()

    with pytest.raises(ResolutionError, match="release_not_found"):
        asyncio.run(
            resolve_run_specification(
                Pool([None, None, None]),
                RunSpecificationSigner(Ed25519PrivateKey.generate(), "key"),
                identity,
                request,
                actor_id=identity.subject,
                idempotency_key="resolve-0003",
            )
        )


def test_reused_run_id_with_changed_request_is_rejected() -> None:
    request, identity = request_and_identity()
    pool = Pool([None, {"request_sha256": "0" * 64}])

    with pytest.raises(ResolutionError, match="run_specification_conflict"):
        asyncio.run(
            resolve_run_specification(
                pool,
                RunSpecificationSigner(Ed25519PrivateKey.generate(), "key"),
                identity,
                request,
                actor_id=identity.subject,
                idempotency_key="resolve-0004",
            )
        )


def test_identical_run_under_new_key_reserves_key_for_original_specification() -> None:
    request, identity = request_and_identity()
    specification_id = uuid4()
    existing = {
        "specification_id": specification_id,
        "run_id": request.run_id,
        "request_sha256": request_sha256(request.canonical_request()),
        "payload": {"specification_id": str(specification_id)},
        "payload_sha256": "d" * 64,
        "signature": b"s" * 64,
        "key_id": "registry-key",
    }
    pool = Pool([None, existing])

    result = asyncio.run(
        resolve_run_specification(
            pool,
            RunSpecificationSigner(Ed25519PrivateKey.generate(), "new-key"),
            identity,
            request,
            actor_id=identity.subject,
            idempotency_key="resolve-0005",
        )
    )

    assert result.specification_id == specification_id
    assert any(
        "INSERT INTO idempotency_records" in query for query, _ in pool.connection.executions
    )
