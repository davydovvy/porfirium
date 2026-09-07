from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import asyncpg

from checkpoint_api.auth import RunCapability
from checkpoint_api.problems import CheckpointProblem


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    checkpoint_id: UUID
    thread_id: UUID
    version: int
    serialization_version: str
    payload: bytes
    payload_sha256: str
    created_at: datetime


def _record(row: asyncpg.Record) -> CheckpointRecord:
    return CheckpointRecord(**dict(row))


async def put_checkpoint(
    pool: asyncpg.Pool,
    *,
    capability: RunCapability,
    checkpoint_id: UUID,
    expected_version: int,
    serialization_version: str,
    payload: bytes,
    payload_sha256: str,
    idempotency_key: str,
) -> CheckpointRecord:
    async with pool.acquire() as connection, connection.transaction():
        lease = await connection.fetchrow(
            "SELECT attempt_id, lease_epoch FROM checkpoint_leases WHERE run_id=$1 FOR UPDATE",
            capability.run_id,
        )
        if lease is None:
            await connection.execute(
                "INSERT INTO checkpoint_leases(run_id, attempt_id, lease_epoch) VALUES($1,$2,$3)",
                capability.run_id,
                capability.attempt_id,
                capability.lease_epoch,
            )
        elif capability.lease_epoch > lease["lease_epoch"]:
            await connection.execute(
                "UPDATE checkpoint_leases SET attempt_id=$2, lease_epoch=$3, updated_at=now() "
                "WHERE run_id=$1",
                capability.run_id,
                capability.attempt_id,
                capability.lease_epoch,
            )
        elif (
            lease["attempt_id"] != capability.attempt_id
            or lease["lease_epoch"] != capability.lease_epoch
        ):
            raise CheckpointProblem(409, "lease_stale", "Attempt lease is stale")

        replay = await connection.fetchrow(
            "SELECT request_hash, checkpoint_id FROM checkpoint_idempotency "
            "WHERE run_id=$1 AND idempotency_key=$2",
            capability.run_id,
            idempotency_key,
        )
        request_hash = (
            f"{checkpoint_id}:{expected_version}:{serialization_version}:{payload_sha256}"
        )
        if replay:
            if replay["request_hash"] != request_hash:
                raise CheckpointProblem(409, "idempotency_conflict", "Idempotency key was reused")
            row = await connection.fetchrow(
                "SELECT checkpoint_id, thread_id, version, serialization_version, payload, "
                "payload_sha256, created_at FROM checkpoints WHERE checkpoint_id=$1",
                replay["checkpoint_id"],
            )
            return _record(row)

        current = await connection.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM checkpoints WHERE thread_id=$1",
            capability.thread_id,
        )
        if current != expected_version:
            raise CheckpointProblem(
                409,
                "checkpoint_version_conflict",
                "Checkpoint version conflicts",
                details={"current_version": current},
            )
        row = await connection.fetchrow(
            "INSERT INTO checkpoints(checkpoint_id, thread_id, run_id, attempt_id, lease_epoch, "
            "version, serialization_version, payload, payload_sha256) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING checkpoint_id, thread_id, version, "
            "serialization_version, payload, payload_sha256, created_at",
            checkpoint_id,
            capability.thread_id,
            capability.run_id,
            capability.attempt_id,
            capability.lease_epoch,
            current + 1,
            serialization_version,
            payload,
            payload_sha256,
        )
        await connection.execute(
            "INSERT INTO checkpoint_idempotency(run_id,idempotency_key,request_hash,checkpoint_id) "
            "VALUES($1,$2,$3,$4)",
            capability.run_id,
            idempotency_key,
            request_hash,
            checkpoint_id,
        )
        event_id = uuid4()
        trace_id = capability.trace_id or capability.run_id.hex
        envelope = {
            "specversion": "1.0", "type": "porfirium.run.checkpoint_committed.v1",
            "id": str(event_id), "source": "checkpoint-api",
            "subject": f"run/{capability.run_id}",
            "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "user_id": str(capability.user_id or capability.run_id),
            "conversation_id": str(capability.conversation_id or capability.thread_id),
            "thread_id": str(capability.thread_id),
            "run_id": str(capability.run_id),
            "attempt_id": str(capability.attempt_id),
            "lease_epoch": capability.lease_epoch,
            "correlation_id": str(UUID(hex=trace_id)),
            "causation_id": str(uuid5(NAMESPACE_URL, f"porfirium:cause:{idempotency_key}")),
            "traceparent": f"00-{trace_id}-{event_id.hex[:16]}-01",
            "schema_version": 1,
            "data": {"run_id": str(capability.run_id), "checkpoint_id": str(checkpoint_id),
                     "checkpoint_version": current + 1, "payload_sha256": payload_sha256},
        }
        await connection.execute(
            "INSERT INTO outbox_events(event_id,subject,payload) "
            "VALUES($1,'porfirium.run.event.checkpoint_committed',$2::jsonb)",
            event_id, json.dumps(envelope, separators=(",", ":")),
        )
        return _record(row)


async def get_checkpoint(
    pool: asyncpg.Pool, thread_id: UUID, checkpoint_id: UUID
) -> CheckpointRecord:
    row = await pool.fetchrow(
        "SELECT checkpoint_id, thread_id, version, serialization_version, payload, payload_sha256, "
        "created_at FROM checkpoints WHERE thread_id=$1 AND checkpoint_id=$2",
        thread_id,
        checkpoint_id,
    )
    if row is None:
        raise CheckpointProblem(404, "checkpoint_not_found", "Checkpoint was not found")
    return _record(row)


async def list_checkpoints(pool: asyncpg.Pool, thread_id: UUID) -> list[CheckpointRecord]:
    rows = await pool.fetch(
        "SELECT checkpoint_id, thread_id, version, serialization_version, payload, payload_sha256, "
        "created_at FROM checkpoints WHERE thread_id=$1 ORDER BY version DESC",
        thread_id,
    )
    return [_record(row) for row in rows]
