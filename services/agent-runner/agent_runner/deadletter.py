from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from cryptography.fernet import Fernet, InvalidToken

from agent_runner.event_validation import EventValidationError, validate_envelope

DLQ_NAMESPACE = UUID("ca17d0ab-542e-4da9-99a8-75cb0351338f")


def delivery_attempt(message: Any) -> int:
    metadata = getattr(message, "metadata", None)
    return max(1, int(getattr(metadata, "num_delivered", 1)))


def event_identity(payload: bytes, envelope: object) -> tuple[UUID, str]:
    if isinstance(envelope, dict):
        try:
            event_id = UUID(str(envelope.get("id")))
        except (TypeError, ValueError):
            event_id = None
        event_type = envelope.get("type")
        if event_id is not None and isinstance(event_type, str) and event_type:
            return event_id, event_type[:128]
    digest = hashlib.sha256(payload).hexdigest()
    return uuid5(DLQ_NAMESPACE, digest), "porfirium.unknown.v1"


def error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code[:64]
    return type(error).__name__.lower()[:64]


def _cipher() -> Fernet:
    key = os.environ.get("RUNNER_DLQ_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("RUNNER_DLQ_ENCRYPTION_KEY is required")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as error:
        raise RuntimeError("RUNNER_DLQ_ENCRYPTION_KEY is invalid") from error


async def dead_letter(
    pool: Any,
    jetstream: Any,
    message: Any,
    *,
    consumer: str,
    error: Exception,
    envelope: object,
) -> UUID:
    now = datetime.now(UTC)
    original_id, original_type = event_identity(message.data, envelope)
    dead_letter_id = uuid5(DLQ_NAMESPACE, f"{consumer}:{original_id}")
    try:
        json.loads(message.data)
        replayable = True
    except (UnicodeDecodeError, json.JSONDecodeError):
        replayable = False
    protected_payload = message.data if replayable else json.dumps(
        {"malformed_sha256": hashlib.sha256(message.data).hexdigest()}, separators=(",", ":")
    ).encode()
    ciphertext = _cipher().encrypt(protected_payload)
    attempts = delivery_attempt(message)
    code = error_code(error)
    await pool.execute(
        """INSERT INTO runner_dead_letters
           (dead_letter_id,original_event_id,original_subject,original_type,consumer,attempts,
            error_code,original_payload_ciphertext,first_failed_at,last_failed_at)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)
           ON CONFLICT (original_event_id,consumer) DO UPDATE SET
             attempts=greatest(runner_dead_letters.attempts,excluded.attempts),
             error_code=excluded.error_code,last_failed_at=excluded.last_failed_at""",
        dead_letter_id,
        original_id,
        str(message.subject)[:256],
        original_type,
        consumer,
        attempts,
        code,
        ciphertext,
        now,
    )
    event_id = uuid4()
    try:
        traced = validate_envelope(envelope)
    except EventValidationError:
        traced = None
    correlation_id = str(traced["correlation_id"]) if traced else str(event_id)
    traceparent = (
        str(traced["traceparent"])
        if traced else f"00-{event_id.hex}-{event_id.hex[:16]}-00"
    )
    diagnostic = {
        "specversion": "1.0",
        "type": "porfirium.dlq.message.v1",
        "id": str(event_id),
        "source": "agent-runner",
        "subject": f"dead-letter/{dead_letter_id}",
        "time": now.isoformat().replace("+00:00", "Z"),
        "user_id": (
            str(traced["user_id"]) if traced else "00000000-0000-0000-0000-000000000000"
        ),
        "correlation_id": correlation_id,
        "causation_id": str(original_id),
        "traceparent": traceparent,
        "schema_version": 1,
        "data": {
            "original_event_id": str(original_id),
            "original_type": original_type,
            "consumer": consumer,
            "attempts": attempts,
            "error_code": code,
            "first_failed_at": now.isoformat().replace("+00:00", "Z"),
            "last_failed_at": now.isoformat().replace("+00:00", "Z"),
        },
    }
    await jetstream.publish(
        "porfirium.dlq.message",
        json.dumps(diagnostic, separators=(",", ":")).encode(),
        headers={"Nats-Msg-Id": str(dead_letter_id), "Event-Id": str(event_id)},
    )
    return dead_letter_id


async def replay(pool: Any, jetstream: Any, dead_letter_id: UUID, operator_id: str) -> bool:
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            "SELECT * FROM runner_dead_letters WHERE dead_letter_id=$1 FOR UPDATE", dead_letter_id
        )
        if row is None:
            return False
        if row["replayed_at"] is not None:
            return True
        try:
            payload_bytes = _cipher().decrypt(bytes(row["original_payload_ciphertext"]))
            payload = json.loads(payload_bytes)
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("dead-letter payload cannot be decrypted") from error
        if "malformed_sha256" in payload:
            raise ValueError("malformed payload cannot be replayed")
        await jetstream.publish(
            row["original_subject"],
            payload_bytes,
            headers={"Nats-Msg-Id": str(row["original_event_id"]),
                     "Event-Id": str(row["original_event_id"])},
        )
        await connection.execute(
            "UPDATE runner_dead_letters SET replayed_at=now(),replayed_by=$2 "
            "WHERE dead_letter_id=$1",
            dead_letter_id,
            operator_id,
        )
        await connection.execute(
            "INSERT INTO runner_operator_audit(audit_id,action,subject_id,operator_id) "
            "VALUES($1,'dead_letter_replay',$2,$3)",
            uuid4(),
            dead_letter_id,
            operator_id,
        )
    return True
