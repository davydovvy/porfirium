from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

MAX_EVENT_BYTES = 1024 * 1024
TRACEPARENT = re.compile(
    r"^00-((?!0{32}-)[0-9a-f]{32})-((?!0{16}-)[0-9a-f]{16})-[0-9a-f]{2}$"
)


class EventValidationError(ValueError):
    code = "event_invalid"


def validate_envelope(envelope: object) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise EventValidationError("event root must be an object")
    try:
        encoded = json.dumps(envelope, separators=(",", ":")).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise EventValidationError("event encoding is invalid") from error
    if len(encoded) > MAX_EVENT_BYTES:
        raise EventValidationError("event exceeds maximum size")
    required = {
        "specversion", "type", "id", "source", "subject", "time", "user_id",
        "conversation_id", "thread_id", "run_id", "correlation_id", "causation_id",
        "traceparent", "schema_version", "data",
    }
    try:
        match = TRACEPARENT.fullmatch(envelope["traceparent"])
        correlation = UUID(str(envelope["correlation_id"]))
        for field in ("id", "user_id", "conversation_id", "thread_id", "run_id", "causation_id"):
            UUID(str(envelope[field]))
        timestamp = datetime.fromisoformat(str(envelope["time"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as error:
        raise EventValidationError("event identity is invalid") from error
    if (
        not required <= envelope.keys()
        or envelope.get("specversion") != "1.0"
        or envelope.get("schema_version") != 1
        or not isinstance(envelope.get("data"), dict)
        or match is None
        or correlation.hex != match.group(1)
        or timestamp.tzinfo is None
    ):
        raise EventValidationError("event contract is invalid")
    return envelope


def validate_run_binding(envelope: dict[str, Any], run: Any) -> None:
    trace_id = UUID(str(envelope["correlation_id"])).hex
    expected = {
        "user_id": run["user_id"],
        "conversation_id": run["conversation_id"],
        "thread_id": run["thread_id"],
        "run_id": run["run_id"],
    }
    if trace_id != run["trace_id"] or any(
        UUID(str(envelope[field])) != value for field, value in expected.items()
    ):
        raise EventValidationError("event is not bound to the admitted run")
