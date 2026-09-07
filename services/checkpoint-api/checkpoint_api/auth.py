from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from uuid import UUID

from fastapi import Header

from checkpoint_api.problems import CheckpointProblem


@dataclass(frozen=True, slots=True)
class RunCapability:
    thread_id: UUID
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int
    operations: frozenset[str]
    user_id: UUID | None = None
    conversation_id: UUID | None = None
    trace_id: str = ""


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode_capability(claims: dict[str, object], secret: str) -> str:
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def decode_capability(token: str, secret: str) -> RunCapability:
    try:
        payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(encoded_signature), expected):
            raise ValueError
        claims = json.loads(_decode(payload))
        if int(claims["exp"]) <= int(time.time()):
            raise ValueError
        trace_id = claims["trace_id"]
        if re.fullmatch(r"(?!0{32}$)[0-9a-f]{32}", trace_id) is None:
            raise ValueError
        return RunCapability(
            UUID(claims["thread_id"]),
            UUID(claims["run_id"]),
            UUID(claims["attempt_id"]),
            int(claims["lease_epoch"]),
            frozenset(claims["operations"]),
            UUID(claims["user_id"]),
            UUID(claims["conversation_id"]),
            trace_id,
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise CheckpointProblem(401, "capability_invalid", "Run capability is invalid") from None


async def authenticated_capability(
    authorization: str | None = Header(default=None),
) -> RunCapability:
    if not authorization or not authorization.startswith("Bearer "):
        raise CheckpointProblem(401, "authentication_required", "Run capability is required")
    secret = os.environ.get("RUN_CAPABILITY_SECRET")
    if not secret:
        raise CheckpointProblem(
            503, "capability_verifier_unavailable", "Capability verifier unavailable", True
        )
    return decode_capability(authorization[7:], secret)
