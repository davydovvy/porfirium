from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from uuid import UUID

from porfirium_agent_sdk import CheckpointClient, PlatformError


def encode_capability(claims: dict[str, object], secret: str) -> str:
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
        )
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def token(attempt_id: UUID, epoch: int) -> str:
    return encode_capability(
        {
            "thread_id": os.environ["THREAD_ID"],
            "run_id": os.environ["RUN_ID"],
            "attempt_id": str(attempt_id),
            "lease_epoch": epoch,
            "user_id": os.environ["RUN_ID"],
            "conversation_id": os.environ["THREAD_ID"],
            "trace_id": UUID(os.environ["RUN_ID"]).hex,
            "operations": ["checkpoint:read", "checkpoint:write"],
            "exp": int(time.time()) + 300,
        },
        os.environ["RUN_CAPABILITY_SECRET"],
    )


def client(attempt_id: UUID, epoch: int) -> CheckpointClient:
    return CheckpointClient(
        base_url="http://checkpoint-api:8107",
        capability=token(attempt_id, epoch),
        thread_id=UUID(os.environ["THREAD_ID"]),
        run_id=UUID(os.environ["RUN_ID"]),
        attempt_id=attempt_id,
        lease_epoch=epoch,
    )


async def write() -> None:
    attempt_id = UUID(os.environ["ATTEMPT_ONE_ID"])
    checkpoint_id = UUID(os.environ["CHECKPOINT_ONE_ID"])
    async with client(attempt_id, 1) as checkpoints:
        first = await checkpoints.put_json(
            {"messages": ["started"], "next": "finish"},
            expected_version=0,
            checkpoint_id=checkpoint_id,
            idempotency_key="phase4-first-checkpoint",
        )
        replay = await checkpoints.put_json(
            {"messages": ["started"], "next": "finish"},
            expected_version=0,
            checkpoint_id=checkpoint_id,
            idempotency_key="phase4-first-checkpoint",
        )
        assert first == replay
        try:
            await checkpoints.put_json(
                {"conflict": True},
                expected_version=0,
                idempotency_key="phase4-version-conflict",
            )
        except PlatformError as error:
            assert error.code == "checkpoint_version_conflict"
        else:
            raise AssertionError("conflicting checkpoint version was accepted")


async def resume() -> None:
    old_attempt = UUID(os.environ["ATTEMPT_ONE_ID"])
    new_attempt = UUID(os.environ["ATTEMPT_TWO_ID"])
    first_id = UUID(os.environ["CHECKPOINT_ONE_ID"])
    async with client(new_attempt, 2) as checkpoints:
        state = await checkpoints.get_json(first_id)
        assert state["next"] == "finish"
        second = await checkpoints.put_json(
            {**state, "messages": [*state["messages"], "finished"], "next": None},
            expected_version=1,
            checkpoint_id=UUID(os.environ["CHECKPOINT_TWO_ID"]),
            idempotency_key="phase4-second-checkpoint",
        )
        assert second.version == 2
    async with client(old_attempt, 1) as stale:
        try:
            await stale.put_json(
                {"stale": True},
                expected_version=2,
                idempotency_key="phase4-stale-checkpoint",
            )
        except PlatformError as error:
            assert error.code == "lease_stale"
        else:
            raise AssertionError("stale lease epoch was accepted")


asyncio.run(write() if os.environ["HARNESS_MODE"] == "write" else resume())
