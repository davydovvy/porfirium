from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID


class CapabilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RunCapability:
    user_id: UUID
    conversation_id: UUID
    thread_id: UUID
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int
    deadline: int


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_capability(token: str, secret: str) -> RunCapability:
    try:
        payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(encoded_signature), expected):
            raise ValueError
        claims = json.loads(_decode(payload))
        if int(claims["exp"]) <= int(time.time()):
            raise ValueError
        if claims.get("audience") not in (None, "agent-runtime-api"):
            raise ValueError
        operations = set(claims.get("operations", []))
        if operations and "runtime:connect" not in operations:
            raise ValueError
        return RunCapability(
            UUID(claims["user_id"]),
            UUID(claims["conversation_id"]),
            UUID(claims["thread_id"]),
            UUID(claims["run_id"]),
            UUID(claims["attempt_id"]),
            int(claims["lease_epoch"]),
            int(claims.get("deadline", claims["exp"])),
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CapabilityError("run capability is invalid") from exc
