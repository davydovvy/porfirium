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
        "trace_id": "1" * 32,
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
    release_id = uuid4()
    delegation_grant_id = uuid4()
    run_input = {
        "trigger_type": "user_message",
        "trigger_id": str(uuid4()),
        "value": "hello",
    }
    capability = decode_capability(
        token(
            "secret",
            run_input=run_input,
            tools=["time.current"],
            release_id=str(release_id),
            delegation_grant_id=str(delegation_grant_id),
        ),
        "secret",
    )
    assert capability.lease_epoch == 3
    assert capability.deadline > time.time()
    assert capability.run_input == run_input
    assert capability.tools == ("time.current",)
    assert capability.release_id == release_id
    assert capability.delegation_grant_id == delegation_grant_id
    assert capability.raw_token


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": 1},
        {"audience": "checkpoint-api"},
        {"operations": ["checkpoint:read"]},
        {"lease_epoch": "invalid"},
        {"run_input": "not-an-object"},
        {"run_input": {"value": "x" * 25000}},
        {"trace_id": "0" * 32},
        {"trace_id": "not-a-trace"},
        {"tools": ["x" * 129]},
    ],
)
def test_invalid_capabilities_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(CapabilityError):
        decode_capability(token("secret", **overrides), "secret")


def test_modified_signature_fails_closed() -> None:
    value = token("secret")
    payload, signature = value.split(".", 1)
    modified = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(CapabilityError):
        decode_capability(f"{payload}.{modified}", "secret")
