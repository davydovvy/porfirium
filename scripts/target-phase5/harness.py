from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from uuid import UUID

from porfirium_agent_sdk import PlatformError, RuntimeClient
from porfirium_agent_sdk.proto import runtime_pb2 as pb


def capability(epoch: int, attempt_id: str) -> str:
    claims = {
        "user_id": os.environ["USER_ID"],
        "conversation_id": os.environ["CONVERSATION_ID"],
        "thread_id": os.environ["THREAD_ID"],
        "run_id": os.environ["RUN_ID"],
        "attempt_id": attempt_id,
        "lease_epoch": epoch,
        "audience": "agent-runtime-api",
        "operations": ["runtime:connect"],
        "deadline": int(time.time()) + 120,
        "exp": int(time.time()) + 120,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        os.environ["RUN_CAPABILITY_SECRET"].encode(), payload.encode(), hashlib.sha256
    ).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def client(epoch: int, attempt_id: str) -> RuntimeClient:
    return RuntimeClient(
        os.environ["RUNTIME_ENDPOINT"], run_id=UUID(os.environ["RUN_ID"]),
        attempt_id=UUID(attempt_id), lease_epoch=epoch,
        run_capability=capability(epoch, attempt_id),
    )


async def main() -> None:
    mode = os.environ["HARNESS_MODE"]
    if mode == "before-restart":
        runtime = client(1, os.environ["ATTEMPT_ONE_ID"])
        await runtime.send(message_started=pb.MessageStarted(
            message_id=os.environ["MESSAGE_ID"], content_type="text/plain"
        ))
        await runtime.send(message_delta=pb.MessageDelta(
            message_id=os.environ["MESSAGE_ID"], chunk_sequence=1, content_utf8=b"restart "
        ))
        await runtime.close()
    elif mode == "after-restart":
        runtime = client(1, os.environ["ATTEMPT_ONE_ID"])
        await runtime.connect()
        assert runtime._last_ack == 2
        await runtime.send(message_delta=pb.MessageDelta(
            message_id=os.environ["MESSAGE_ID"], chunk_sequence=2, content_utf8=b"safe"
        ))
        content = b"restart safe"
        await runtime.send(message_completed=pb.MessageCompleted(
            message_id=os.environ["MESSAGE_ID"], canonical_content_utf8=content,
            chunk_count=2, content_bytes=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(), finish_reason="stop",
        ))
        await runtime.close()
    elif mode == "fence":
        fresh = client(2, os.environ["ATTEMPT_TWO_ID"])
        await fresh.connect()
        await fresh.send(heartbeat=pb.Heartbeat())
        await fresh.close()
        stale = client(1, os.environ["ATTEMPT_ONE_ID"])
        try:
            await stale.connect()
        except PlatformError as exc:
            assert exc.code == "capability_invalid"
        else:
            raise AssertionError("old epoch was accepted")
    else:
        raise AssertionError(mode)


asyncio.run(main())
