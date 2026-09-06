from __future__ import annotations

import time
from uuid import uuid4

import pytest

from checkpoint_api.auth import decode_capability, encode_capability
from checkpoint_api.problems import CheckpointProblem


def claims() -> dict[str, object]:
    return {
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "lease_epoch": 2,
        "operations": ["checkpoint:read", "checkpoint:write"],
        "exp": int(time.time()) + 60,
    }


def test_signed_capability_round_trip() -> None:
    source = claims()
    capability = decode_capability(encode_capability(source, "secret"), "secret")
    assert str(capability.thread_id) == source["thread_id"]
    assert capability.lease_epoch == 2


def test_tampered_capability_is_rejected() -> None:
    token = encode_capability(claims(), "secret")
    with pytest.raises(CheckpointProblem, match="Run capability is invalid"):
        decode_capability(token + "x", "secret")
