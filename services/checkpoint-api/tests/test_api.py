from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

import checkpoint_api.main as checkpoint_main
from checkpoint_api.auth import RunCapability, authenticated_capability
from checkpoint_api.main import app
from checkpoint_api.store import CheckpointRecord


def capability(thread_id=None) -> RunCapability:
    return RunCapability(
        thread_id or uuid4(),
        uuid4(),
        uuid4(),
        1,
        frozenset({"checkpoint:read", "checkpoint:write"}),
    )


def test_put_validates_and_passes_identity(monkeypatch: object) -> None:
    cap = capability()
    app.dependency_overrides[authenticated_capability] = lambda: cap
    app.state.pool = object()
    payload = b'{"step":1}'
    checkpoint_id = uuid4()

    async def put(*args: object, **kwargs: object) -> CheckpointRecord:
        assert kwargs["capability"] == cap
        assert kwargs["payload"] == payload
        return CheckpointRecord(
            checkpoint_id,
            cap.thread_id,
            1,
            "json-v1",
            payload,
            hashlib.sha256(payload).hexdigest(),
            datetime.now(UTC),
        )

    monkeypatch.setattr(checkpoint_main, "put_checkpoint", put)
    response = TestClient(app).put(
        f"/v1/threads/{cap.thread_id}/checkpoints/{checkpoint_id}",
        headers={"Idempotency-Key": "checkpoint-1234"},
        json={
            "run_id": str(cap.run_id),
            "attempt_id": str(cap.attempt_id),
            "lease_epoch": 1,
            "expected_version": 0,
            "serialization_version": "json-v1",
            "payload": base64.b64encode(payload).decode(),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    app.dependency_overrides.clear()


def test_wrong_namespace_is_forbidden() -> None:
    cap = capability()
    app.dependency_overrides[authenticated_capability] = lambda: cap
    response = TestClient(app).get(f"/v1/threads/{uuid4()}/checkpoints")
    assert response.status_code == 403
    assert response.json()["code"] == "checkpoint_forbidden"
    app.dependency_overrides.clear()


def test_hash_mismatch_is_bounded_problem() -> None:
    cap = capability()
    app.dependency_overrides[authenticated_capability] = lambda: cap
    response = TestClient(app).put(
        f"/v1/threads/{cap.thread_id}/checkpoints/{uuid4()}",
        headers={"Idempotency-Key": "checkpoint-1234"},
        json={
            "run_id": str(cap.run_id),
            "attempt_id": str(cap.attempt_id),
            "lease_epoch": 1,
            "expected_version": 0,
            "serialization_version": "json-v1",
            "payload": base64.b64encode(b"payload").decode(),
            "payload_sha256": "0" * 64,
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "payload_hash_mismatch"
    app.dependency_overrides.clear()
