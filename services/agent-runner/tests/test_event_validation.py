from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agent_runner.event_validation import (
    EventValidationError,
    validate_envelope,
    validate_run_binding,
)


def envelope() -> dict[str, object]:
    trace_id = "1" * 32
    return {
        "specversion": "1.0",
        "type": "porfirium.run.result_proposed.v1",
        "id": str(uuid4()),
        "source": "agent-runtime-api",
        "subject": "run/example",
        "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "user_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "correlation_id": str(UUID(hex=trace_id)),
        "causation_id": str(uuid4()),
        "traceparent": f"00-{trace_id}-{'2' * 16}-01",
        "schema_version": 1,
        "data": {},
    }


def test_validates_trace_correlation_and_run_binding() -> None:
    value = validate_envelope(envelope())
    run = {field: UUID(str(value[field])) for field in (
        "user_id", "conversation_id", "thread_id", "run_id"
    )}
    run["trace_id"] = UUID(str(value["correlation_id"])).hex
    validate_run_binding(value, run)


@pytest.mark.parametrize("field", ["traceparent", "correlation_id", "causation_id", "time"])
def test_rejects_missing_trace_metadata(field: str) -> None:
    value = envelope()
    value.pop(field)
    with pytest.raises(EventValidationError):
        validate_envelope(value)


def test_rejects_trace_mismatch_and_oversized_payload() -> None:
    value = envelope()
    value["correlation_id"] = str(uuid4())
    with pytest.raises(EventValidationError):
        validate_envelope(value)

    value = envelope()
    value["data"] = {"content": "x" * (1024 * 1024)}
    with pytest.raises(EventValidationError, match="maximum size"):
        validate_envelope(value)
