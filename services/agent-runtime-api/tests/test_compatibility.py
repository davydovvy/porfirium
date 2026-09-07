from uuid import uuid4

import pytest

from agent_runtime_api.auth import RunCapability
from agent_runtime_api.proto import runtime_pb2 as pb
from agent_runtime_api.runtime import _validate_identity


def capability() -> RunCapability:
    return RunCapability(
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), 2, 9999999999, None, None, ()
    )


def identity(value: RunCapability, protocol: str) -> pb.FrameIdentity:
    return pb.FrameIdentity(
        protocol_version=protocol,
        run_id=str(value.run_id),
        attempt_id=str(value.attempt_id),
        lease_epoch=value.lease_epoch,
        sequence=1,
        idempotency_key="compatible-frame",
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
