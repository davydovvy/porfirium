from uuid import UUID, uuid4

import pytest

from agent_runtime_api.auth import RunCapability
from agent_runtime_api.proto import runtime_pb2 as pb
from agent_runtime_api.runtime import _event, _validate_identity


def capability() -> RunCapability:
    return RunCapability(
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 2, 9999999999, None, None, (), "1" * 32
    )


def identity(value: RunCapability, protocol: str) -> pb.FrameIdentity:
    return pb.FrameIdentity(
        protocol_version=protocol,
        run_id=str(value.run_id),
        attempt_id=str(value.attempt_id),
        lease_epoch=value.lease_epoch,
        sequence=1,
        idempotency_key="compatible-frame",
        traceparent=f"00-{value.trace_id}-{'2' * 16}-01",
    )


@pytest.mark.parametrize("protocol", ["1.0", "1.1"])
def test_accepts_current_and_adjacent_additive_minor(protocol: str) -> None:
    value = capability()
    _validate_identity(identity(value, protocol), value)


@pytest.mark.parametrize("protocol", ["0.9", "1.2", "2.0", "invalid"])
def test_rejects_protocol_outside_explicit_window(protocol: str) -> None:
    value = capability()
    with pytest.raises(ValueError, match="unsupported_protocol"):
        _validate_identity(identity(value, protocol), value)


def test_rejects_trace_not_bound_to_signed_capability() -> None:
    value = capability()
    frame_identity = identity(value, "1.0")
    frame_identity.traceparent = f"00-{'4' * 32}-{'2' * 16}-01"
    with pytest.raises(ValueError, match="identity_mismatch"):
        _validate_identity(frame_identity, value)


def test_durable_event_preserves_trace_and_has_uuid_causation() -> None:
    value = capability()
    frame = pb.AgentFrame(
        identity=identity(value, "1.0"),
        message_started=pb.MessageStarted(message_id=str(uuid4()), content_type="text/plain"),
    )
    _, event = _event(value, frame, uuid4())
    assert event["traceparent"] == frame.identity.traceparent
    assert event["correlation_id"] == str(UUID(hex=value.trace_id))
    UUID(event["causation_id"])
