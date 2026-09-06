from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from porfirium_agent_sdk.errors import PlatformError


@dataclass(frozen=True, slots=True)
class CheckpointMetadata:
    checkpoint_id: UUID
    thread_id: UUID
    version: int
    serialization_version: str
    payload_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Checkpoint(CheckpointMetadata):
    payload: bytes


class CheckpointClient:
    def __init__(
        self,
        *,
        base_url: str,
        capability: str,
        thread_id: UUID,
        run_id: UUID,
        attempt_id: UUID,
        lease_epoch: int,
        timeout: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.lease_epoch = lease_epoch
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {capability}"},
        )

    async def __aenter__(self) -> CheckpointClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _metadata(self, data: dict[str, Any]) -> CheckpointMetadata:
        return CheckpointMetadata(
            checkpoint_id=UUID(data["checkpoint_id"]),
            thread_id=UUID(data["thread_id"]),
            version=data["version"],
            serialization_version=data["serialization_version"],
            payload_sha256=data["payload_sha256"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def _raise(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            problem = response.json()
        except ValueError:
            problem = {}
        raise PlatformError(
            problem.get("code", "platform_error"),
            problem.get("title", "Platform request failed"),
            retryable=problem.get("retryable", False),
            correlation_id=problem.get("correlation_id"),
            details=problem.get("details"),
        )

    async def put(
        self,
        payload: bytes,
        *,
        expected_version: int,
        serialization_version: str = "json-v1",
        checkpoint_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> CheckpointMetadata:
        checkpoint_id = checkpoint_id or uuid4()
        idempotency_key = idempotency_key or str(uuid4())
        digest = hashlib.sha256(payload).hexdigest()
        response = await self._client.put(
            f"/v1/threads/{self.thread_id}/checkpoints/{checkpoint_id}",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "run_id": str(self.run_id),
                "attempt_id": str(self.attempt_id),
                "lease_epoch": self.lease_epoch,
                "expected_version": expected_version,
                "serialization_version": serialization_version,
                "payload": base64.b64encode(payload).decode(),
                "payload_sha256": digest,
            },
        )
        self._raise(response)
        return self._metadata(response.json())

    async def get(self, checkpoint_id: UUID) -> Checkpoint:
        response = await self._client.get(
            f"/v1/threads/{self.thread_id}/checkpoints/{checkpoint_id}"
        )
        self._raise(response)
        data = response.json()
        item = self._metadata(data)
        return Checkpoint(
            checkpoint_id=item.checkpoint_id,
            thread_id=item.thread_id,
            version=item.version,
            serialization_version=item.serialization_version,
            payload_sha256=item.payload_sha256,
            created_at=item.created_at,
            payload=base64.b64decode(data["payload"], validate=True),
        )

    async def list(self) -> list[CheckpointMetadata]:
        response = await self._client.get(f"/v1/threads/{self.thread_id}/checkpoints")
        self._raise(response)
        return [self._metadata(data) for data in response.json()]

    async def put_json(
        self, value: Any, *, expected_version: int, **kwargs: Any
    ) -> CheckpointMetadata:
        return await self.put(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode(),
            expected_version=expected_version,
            serialization_version="json-v1",
            **kwargs,
        )

    async def get_json(self, checkpoint_id: UUID) -> Any:
        return json.loads((await self.get(checkpoint_id)).payload)
