from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from agent_runner.capability import issue_run_capability
from agent_runner.container import AttemptContainer, ContainerBackend
from agent_runner.models import RunAdmission, RunResponse, SignedSpecification
from agent_runner.outbox import enqueue


class RunnerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class RunnerService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        backend: ContainerBackend,
        *,
        capability_secret: str,
        runtime_url: str,
        attempt_timeout_seconds: int = 300,
    ) -> None:
        self.pool = pool
        self.backend = backend
        self.capability_secret = capability_secret
        self.runtime_url = runtime_url
        self.attempt_timeout_seconds = attempt_timeout_seconds

    async def admit(
        self, admission: RunAdmission, idempotency_key: str, spec: SignedSpecification
    ) -> RunResponse:
        request_digest = canonical_digest(admission.model_dump(mode="json"))
        async with self.pool.acquire() as connection, connection.transaction():
            replay = await connection.fetchrow(
                "SELECT request_sha256, run_id FROM run_idempotency "
                "WHERE operation='admit' AND idempotency_key=$1", idempotency_key
            )
            if replay:
                if replay["request_sha256"] != request_digest:
                    raise RunnerError("idempotency_conflict")
                return _run(await _get_run(connection, replay["run_id"]))
            if await connection.fetchval("SELECT 1 FROM runs WHERE run_id=$1", admission.run_id):
                raise RunnerError("run_conflict")
            payload_digest = canonical_digest(spec.payload)
            if payload_digest != spec.payload_sha256 or spec.run_id != admission.run_id:
                raise RunnerError("specification_invalid")
            expires_at = _parse_time(spec.payload.get("expires_at"))
            deadline = min(
                expires_at, datetime.now(UTC) + timedelta(seconds=self.attempt_timeout_seconds)
            )
            await connection.execute(
                """INSERT INTO runs
                   (run_id,user_id,conversation_id,thread_id,release_id,delegation_grant_id,
                    configuration_revision_id,starting_checkpoint_id,trigger,trace_id,
                    specification,specification_sha256,deadline_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11::jsonb,$12,$13)""",
                admission.run_id, admission.user_id, admission.conversation_id,
                admission.thread_id, admission.release_id, admission.delegation_grant_id,
                admission.configuration_revision_id, admission.starting_checkpoint_id,
                json.dumps(admission.trigger.model_dump(mode="json")), admission.trace_id,
                json.dumps(spec.model_dump(mode="json")), spec.payload_sha256, deadline,
            )
            await connection.execute(
                "INSERT INTO run_idempotency(operation,idempotency_key,request_sha256,run_id) "
                "VALUES('admit',$1,$2,$3)", idempotency_key, request_digest, admission.run_id
            )
            await enqueue(
                connection, event_id=uuid4(), subject="runner.run.schedule.v1",
                payload={"run_id": str(admission.run_id)},
            )
            return _run(await _get_run(connection, admission.run_id))

    async def get(self, run_id: UUID) -> RunResponse:
        async with self.pool.acquire() as connection:
            return _run(await _get_run(connection, run_id))

    async def schedule(self, run_id: UUID) -> UUID | None:
        attempt_id = uuid4()
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow("SELECT * FROM runs WHERE run_id=$1 FOR UPDATE", run_id)
            if row is None:
                raise RunnerError("run_not_found")
            if row["state"] not in ("accepted", "scheduled") or row["active_attempt_id"]:
                return None
            epoch = row["lease_epoch"] + 1
            number = await connection.fetchval(
                "SELECT coalesce(max(attempt_number),0)+1 FROM attempts WHERE run_id=$1", run_id
            )
            name = f"porfirium-run-{run_id}-attempt-{number}"
            await connection.execute(
                "INSERT INTO attempts(attempt_id,run_id,attempt_number,lease_epoch,container_name,"
                "deadline_at) VALUES($1,$2,$3,$4,$5,$6)",
                attempt_id, run_id, number, epoch, name, row["deadline_at"]
            )
            await connection.execute(
                "UPDATE runs SET state='starting',active_attempt_id=$2,lease_epoch=$3,"
                "updated_at=now() "
                "WHERE run_id=$1", run_id, attempt_id, epoch
            )
        await self._start_attempt(run_id, attempt_id)
        return attempt_id

    async def _start_attempt(self, run_id: UUID, attempt_id: UUID) -> None:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT r.*,a.container_name,a.attempt_id FROM runs r JOIN attempts a "
                "ON a.attempt_id=r.active_attempt_id WHERE r.run_id=$1 AND a.attempt_id=$2",
                run_id, attempt_id,
            )
        spec = _object(row["specification"])
        payload = _object(spec["payload"])
        release = _object(payload["release"])
        resources = _object(payload["resources"])
        image = release["image"]
        if not isinstance(image, str) or not re.search(r"@sha256:[0-9a-f]{64}$", image):
            raise RunnerError("specification_invalid")
        capability = issue_run_capability(
            {"user_id": str(row["user_id"]), "conversation_id": str(row["conversation_id"]),
             "thread_id": str(row["thread_id"]), "run_id": str(run_id),
             "attempt_id": str(attempt_id), "lease_epoch": row["lease_epoch"]},
            self.capability_secret, row["deadline_at"],
        )
        container = AttemptContainer(
            row["container_name"], image, capability, self.runtime_url,
            min(_memory_bytes(resources.get("memory", "256Mi")), 268435456),
            min(_cpu(resources.get("cpu", "1")), 1.0),
            min(int(resources.get("pids", 64)), 64),
        )
        try:
            container_id = await self.backend.create(container)
            async with self.pool.acquire() as connection:
                await connection.execute(
                    "UPDATE attempts SET container_id=$2 WHERE attempt_id=$1",
                    attempt_id,
                    container_id,
                )
            await self.backend.start(container_id)
            async with self.pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "UPDATE attempts SET state='running',started_at=now() WHERE attempt_id=$1",
                    attempt_id,
                )
                await connection.execute(
                    "UPDATE runs SET state='running',updated_at=now() WHERE run_id=$1 "
                    "AND active_attempt_id=$2", run_id, attempt_id
                )
        except Exception:
            await self._fail_start(run_id, attempt_id)
            raise

    async def _fail_start(self, run_id: UUID, attempt_id: UUID) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "UPDATE attempts SET state='failed',ended_at=now() WHERE attempt_id=$1", attempt_id
            )
            await connection.execute(
                "UPDATE runs SET state='failed',terminal_code='attempt_start_failed',"
                "active_attempt_id=NULL,updated_at=now() WHERE run_id=$1 AND active_attempt_id=$2",
                run_id, attempt_id,
            )

    async def cancel(self, run_id: UUID, idempotency_key: str) -> RunResponse:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow("SELECT * FROM runs WHERE run_id=$1 FOR UPDATE", run_id)
            if row is None:
                raise RunnerError("run_not_found")
            if row["state"] in ("completed", "failed", "cancelled"):
                return _run(row)
            attempt = None
            if row["active_attempt_id"]:
                attempt = await connection.fetchrow(
                    "SELECT * FROM attempts WHERE attempt_id=$1", row["active_attempt_id"]
                )
                await connection.execute(
                    "UPDATE attempts SET state='stopping' WHERE attempt_id=$1",
                    row["active_attempt_id"],
                )
            await connection.execute(
                "UPDATE runs SET state='cancelling',cancellation_requested_at=coalesce("
                "cancellation_requested_at,now()),updated_at=now() WHERE run_id=$1", run_id
            )
        if attempt and attempt["container_id"]:
            await self.backend.remove(attempt["container_id"])
        async with self.pool.acquire() as connection, connection.transaction():
            if attempt:
                await connection.execute(
                    "UPDATE attempts SET state='exited',ended_at=now() WHERE attempt_id=$1",
                    attempt["attempt_id"],
                )
            await connection.execute(
                "UPDATE runs SET state='cancelled',terminal_code='cancelled',"
                "active_attempt_id=NULL,"
                "updated_at=now() WHERE run_id=$1 AND state='cancelling'", run_id
            )
            event_id = uuid4()
            await enqueue(
                connection, event_id=event_id, subject="porfirium.run.event.cancelled",
                payload={
                    "specversion": "1.0", "type": "porfirium.run.cancelled.v1",
                    "id": str(event_id), "source": "agent-runner", "run_id": str(run_id),
                    "schema_version": 1,
                    "data": {"run_id": str(run_id), "state": "cancelled",
                             "attempt_id": str(attempt["attempt_id"]) if attempt else None,
                             "lease_epoch": row["lease_epoch"] or None, "code": "cancelled"},
                },
            )
            return _run(await _get_run(connection, run_id))

    async def reconcile(self) -> int:
        rows = await self.pool.fetch(
            "SELECT r.run_id,r.user_id,r.conversation_id,r.thread_id,r.lease_epoch,"
            "a.attempt_id,a.container_id,a.visible_output,a.active_message_id "
            "FROM runs r JOIN attempts a "
            "ON a.attempt_id=r.active_attempt_id "
            "WHERE r.state IN ('starting','running','cancelling')"
        )
        repaired = 0
        for row in rows:
            exists = bool(row["container_id"]) and await self.backend.exists(row["container_id"])
            if not exists:
                await self._handle_attempt_loss(row)
                repaired += 1
        return repaired

    async def _handle_attempt_loss(self, attempt: Any) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "UPDATE attempts SET state='failed',ended_at=now() WHERE attempt_id=$1",
                attempt["attempt_id"],
            )
            if not attempt["visible_output"]:
                await connection.execute(
                    "UPDATE runs SET state='scheduled',active_attempt_id=NULL,updated_at=now() "
                    "WHERE run_id=$1 AND active_attempt_id=$2",
                    attempt["run_id"], attempt["attempt_id"],
                )
                return
            await connection.execute(
                "UPDATE runs SET state='failed',terminal_code='attempt_lost_after_output',"
                "active_attempt_id=NULL,updated_at=now() WHERE run_id=$1 AND active_attempt_id=$2",
                attempt["run_id"], attempt["attempt_id"],
            )
            if attempt["active_message_id"]:
                event_id = uuid4()
                await enqueue(
                    connection, event_id=event_id,
                    subject="porfirium.conversation.event.message_interrupted",
                    payload={
                        "specversion": "1.0", "type": "porfirium.message.interrupted.v1",
                        "id": str(event_id), "source": "agent-runner",
                        "user_id": str(attempt["user_id"]),
                        "conversation_id": str(attempt["conversation_id"]),
                        "thread_id": str(attempt["thread_id"]),
                        "run_id": str(attempt["run_id"]),
                        "attempt_id": str(attempt["attempt_id"]),
                        "lease_epoch": attempt["lease_epoch"],
                        "data": {"message_id": str(attempt["active_message_id"]),
                                 "code": "attempt_lost"}, "schema_version": 1,
                    },
                )


async def _get_run(connection: Any, run_id: UUID) -> Any:
    row = await connection.fetchrow("SELECT * FROM runs WHERE run_id=$1", run_id)
    if row is None:
        raise RunnerError("run_not_found")
    return row


def _run(row: Any) -> RunResponse:
    return RunResponse(**{key: row[key] for key in RunResponse.model_fields})


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise RunnerError("specification_invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed <= datetime.now(UTC):
        raise RunnerError("specification_expired")
    return parsed


def _object(value: object) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RunnerError("specification_invalid")
    return decoded


def _cpu(value: object) -> float:
    try:
        result = float(str(value)[:-1]) / 1000 if str(value).endswith("m") else float(value)
    except (TypeError, ValueError) as error:
        raise RunnerError("specification_invalid") from error
    if result <= 0:
        raise RunnerError("specification_invalid")
    return result


def _memory_bytes(value: object) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)(Mi|Gi)", str(value))
    if not match:
        raise RunnerError("specification_invalid")
    multiplier = 1024**2 if match.group(2) == "Mi" else 1024**3
    return int(match.group(1)) * multiplier
