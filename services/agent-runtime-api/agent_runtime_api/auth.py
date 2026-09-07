from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
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
    run_input: dict[str, Any] | None
    starting_checkpoint_id: UUID | None
    models: tuple[str, ...]
    trace_id: str = ""
    tools: tuple[str, ...] = ()
    release_id: UUID | None = None
    delegation_grant_id: UUID | None = None
    raw_token: str = field(default="", repr=False, compare=False)


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
        run_input = claims.get("run_input")
        if run_input is not None and (
            not isinstance(run_input, dict) or len(json.dumps(run_input).encode()) > 24576
        ):
            raise ValueError
        starting_checkpoint = claims.get("starting_checkpoint_id")
        models = claims.get("models", [])
        tools = claims.get("tools", [])
        release_id = claims.get("release_id")
        delegation_grant_id = claims.get("delegation_grant_id")
        trace_id = claims["trace_id"]
        if (
            not isinstance(models, list)
            or len(models) > 16
            or any(not isinstance(model, str) or not model for model in models)
            or not isinstance(tools, list)
            or len(tools) > 64
            or any(not isinstance(tool, str) or not tool or len(tool) > 128 for tool in tools)
            or not isinstance(trace_id, str)
            or re.fullmatch(r"(?!0{32}$)[0-9a-f]{32}", trace_id) is None
        ):
            raise ValueError
        return RunCapability(
            UUID(claims["user_id"]),
            UUID(claims["conversation_id"]),
            UUID(claims["thread_id"]),
            UUID(claims["run_id"]),
            UUID(claims["attempt_id"]),
            int(claims["lease_epoch"]),
            int(claims.get("deadline", claims["exp"])),
            run_input,
            UUID(starting_checkpoint) if starting_checkpoint else None,
            tuple(models),
            trace_id,
            tuple(tools),
            UUID(release_id) if release_id else None,
            UUID(delegation_grant_id) if delegation_grant_id else None,
            token,
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CapabilityError("run capability is invalid") from exc
