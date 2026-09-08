from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from agent_runner.event_validation import validate_envelope, validate_run_binding
from agent_runner.outbox import enqueue

TERMINAL_STATES = {"completed", "failed", "cancelled"}


class CompletionError(ValueError):
    pass


async def consume_run_event(pool: asyncpg.Pool, envelope: dict[str, Any]) -> bool:
    """Apply a completion event once and converge the run without changing terminal outcomes."""
    validate_envelope(envelope)
    try:
        event_id = UUID(str(envelope["id"]))
        event_type = str(envelope["type"])
        run_id = UUID(str(envelope["run_id"]))
        data = envelope["data"]
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError("event_invalid") from exc

    async with pool.acquire() as connection, connection.transaction():
        inserted = await connection.fetchval(
            "INSERT INTO run_event_inbox(event_id,event_type) VALUES($1,$2) "
            "ON CONFLICT DO NOTHING RETURNING event_id",
            event_id,
            event_type,
        )
        if inserted is None:
            return False
        run = await connection.fetchrow("SELECT * FROM runs WHERE run_id=$1 FOR UPDATE", run_id)
        if run is None:
            raise CompletionError("run_not_found")
        validate_run_binding(envelope, run)
        if event_type == "porfirium.run.result_proposed.v1":
            await _proposal(connection, run, event_id, data)
        elif event_type == "porfirium.run.messages_committed.v1":
            await _confirmation(connection, run_id, "messages", data)
        elif event_type == "porfirium.run.checkpoint_committed.v1":
            await _confirmation(connection, run_id, "checkpoint", data)
        elif event_type == "porfirium.message.started.v1":
            attempt_id = UUID(str(envelope["attempt_id"]))
            if (
                attempt_id != run["active_attempt_id"]
                or int(envelope["lease_epoch"]) != run["lease_epoch"]
            ):
                raise CompletionError("stale_epoch")
            await connection.execute(
                "UPDATE attempts SET visible_output=true,active_message_id=$2 WHERE attempt_id=$1",
                attempt_id, UUID(str(data["message_id"])),
            )
        else:
            raise CompletionError("event_unsupported")
        if event_type.startswith("porfirium.run."):
            await _converge(connection, run_id)
    return True


async def _proposal(connection: Any, run: Any, event_id: UUID, data: dict[str, Any]) -> None:
    attempt_id = UUID(str(data["attempt_id"]))
    lease_epoch = int(data["lease_epoch"])
    if attempt_id != run["active_attempt_id"] or lease_epoch != run["lease_epoch"]:
        raise CompletionError("stale_epoch")
    required = list(dict.fromkeys(data.get("required_confirmations", [])))
    if not set(required) <= {"messages", "checkpoint"}:
        raise CompletionError("confirmation_invalid")
    message_ids = [UUID(str(value)) for value in data.get("final_message_ids", [])]
    checkpoint_id = data.get("final_checkpoint_id")
    if ("messages" in required) != bool(message_ids):
        raise CompletionError("confirmation_invalid")
    if ("checkpoint" in required) != bool(checkpoint_id):
        raise CompletionError("confirmation_invalid")
    existing = await connection.fetchrow(
        "SELECT * FROM run_completion WHERE run_id=$1", run["run_id"]
    )
    if existing:
        same = (
            existing["attempt_id"] == attempt_id
            and existing["lease_epoch"] == lease_epoch
            and list(existing["final_message_ids"]) == message_ids
            and existing["final_checkpoint_id"]
            == (UUID(str(checkpoint_id)) if checkpoint_id else None)
            and list(existing["required_confirmations"]) == required
        )
        if not same:
            raise CompletionError("proposal_conflict")
        return
    await connection.execute(
        "INSERT INTO run_completion(run_id,proposal_event_id,attempt_id,lease_epoch,"
        "final_message_ids,final_checkpoint_id,required_confirmations) "
        "VALUES($1,$2,$3,$4,$5,$6,$7)",
        run["run_id"], event_id, attempt_id, lease_epoch, message_ids,
        UUID(str(checkpoint_id)) if checkpoint_id else None, required,
    )
    if run["state"] not in TERMINAL_STATES:
        await connection.execute(
            "UPDATE runs SET state='completion_reconciling',updated_at=now() WHERE run_id=$1",
            run["run_id"],
        )


async def _confirmation(
    connection: Any, run_id: UUID, confirmation: str, data: dict[str, Any]
) -> None:
    await connection.execute(
        "INSERT INTO run_confirmations(run_id,confirmation,payload) VALUES($1,$2,$3::jsonb) "
        "ON CONFLICT(run_id,confirmation) DO UPDATE SET payload=excluded.payload",
        run_id,
        confirmation,
        json.dumps(data, separators=(",", ":")),
    )
    proposal = await connection.fetchrow("SELECT * FROM run_completion WHERE run_id=$1", run_id)
    if proposal is None:
        return
    if confirmation == "messages":
        actual = {UUID(str(value)) for value in data.get("message_ids", [])}
        if actual != set(proposal["final_message_ids"]):
            raise CompletionError("confirmation_mismatch")
        await connection.execute(
            "UPDATE run_completion SET messages_confirmed=true WHERE run_id=$1", run_id
        )
    else:
        if UUID(str(data.get("checkpoint_id"))) != proposal["final_checkpoint_id"]:
            raise CompletionError("confirmation_mismatch")
        await connection.execute(
            "UPDATE run_completion SET checkpoint_confirmed=true WHERE run_id=$1", run_id
        )


async def _converge(connection: Any, run_id: UUID) -> None:
    proposal = await connection.fetchrow("SELECT * FROM run_completion WHERE run_id=$1", run_id)
    if proposal:
        confirmations = await connection.fetch(
            "SELECT confirmation,payload FROM run_confirmations WHERE run_id=$1", run_id
        )
        for confirmation in confirmations:
            payload = confirmation["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if confirmation["confirmation"] == "messages":
                actual = {UUID(str(value)) for value in payload.get("message_ids", [])}
                if actual == set(proposal["final_message_ids"]):
                    await connection.execute(
                        "UPDATE run_completion SET messages_confirmed=true WHERE run_id=$1", run_id
                    )
            elif UUID(str(payload.get("checkpoint_id"))) == proposal["final_checkpoint_id"]:
                await connection.execute(
                    "UPDATE run_completion SET checkpoint_confirmed=true WHERE run_id=$1", run_id
                )
    row = await connection.fetchrow(
        "SELECT r.state,r.active_attempt_id,r.user_id,r.conversation_id,r.thread_id,r.trace_id,"
        "c.* FROM runs r JOIN run_completion c USING(run_id) "
        "WHERE r.run_id=$1",
        run_id,
    )
    if row is None or row["state"] in TERMINAL_STATES:
        return
    required = set(row["required_confirmations"])
    ready = ("messages" not in required or row["messages_confirmed"]) and (
        "checkpoint" not in required or row["checkpoint_confirmed"]
    )
    if not ready:
        return
    await connection.execute(
        "UPDATE attempts SET state='exited',ended_at=coalesce(ended_at,now()) WHERE attempt_id=$1",
        row["attempt_id"],
    )
    changed = await connection.fetchval(
        "UPDATE runs SET state='completed',terminal_code=NULL,active_attempt_id=NULL,"
        "updated_at=now() "
        "WHERE run_id=$1 AND state='completion_reconciling' RETURNING run_id",
        run_id,
    )
    if changed:
        await connection.execute(
            "UPDATE run_completion SET reconciled_at=now() WHERE run_id=$1", run_id
        )
        event_id = uuid4()
        trace_id = str(row["trace_id"])
        await enqueue(
            connection,
            event_id=event_id,
            subject="porfirium.run.event.completed",
            payload={
                "specversion": "1.0", "type": "porfirium.run.completed.v1",
                "id": str(event_id), "source": "agent-runner",
                "subject": f"run/{run_id}",
                "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "user_id": str(row["user_id"]),
                "conversation_id": str(row["conversation_id"]),
                "thread_id": str(row["thread_id"]),
                "run_id": str(run_id),
                "correlation_id": str(UUID(hex=trace_id)),
                "causation_id": str(row["proposal_event_id"]),
                "traceparent": f"00-{trace_id}-{event_id.hex[:16]}-01",
                "data": {
                    "run_id": str(run_id), "state": "completed",
                    "attempt_id": str(row["attempt_id"]),
                    "lease_epoch": row["lease_epoch"], "code": None,
                },
                "schema_version": 1,
            },
        )
