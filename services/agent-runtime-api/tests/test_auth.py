from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest

from agent_runtime_api.auth import CapabilityError, decode_capability


def token(secret: str, **overrides) -> str:
    claims = {
        "user_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "lease_epoch": 3,
        "audience": "agent-runtime-api",
        "operations": ["runtime:connect"],
        "deadline": int(time.time()) + 30,
        "exp": int(time.time()) + 30,
    }
    claims.update(overrides)
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def test_valid_capability_is_bound_to_attempt_epoch_and_runtime_audience() -> None:
    capability = decode_capability(token("secret"), "secret")
    assert capability.lease_epoch == 3
    assert capability.deadline > time.time()


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": 1},
        {"audience": "checkpoint-api"},
        {"operations": ["checkpoint:read"]},
        {"lease_epoch": "invalid"},
    ],
)
def test_invalid_capabilities_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(CapabilityError):
        decode_capability(token("secret", **overrides), "secret")


def test_modified_signature_fails_closed() -> None:
    value = token("secret")
    with pytest.raises(CapabilityError):
        decode_capability(value[:-1] + ("A" if value[-1] != "A" else "B"), "secret")
