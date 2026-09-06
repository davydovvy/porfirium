from __future__ import annotations

from typing import Any, NoReturn
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from google.protobuf.struct_pb2 import Struct

from porfirium_agent_sdk.checkpoints import CheckpointClient
from porfirium_agent_sdk.proto import runtime_pb2 as pb
from porfirium_agent_sdk.runtime import RuntimeClient


class InputSuspended(Exception):
    """Signals that the activation committed human input state and must exit."""

    def __init__(self, suspension_id: UUID, input_request_id: UUID) -> None:
        super().__init__("activation suspended for human input")
        self.suspension_id = suspension_id
        self.input_request_id = input_request_id


async def request_input(
    runtime: RuntimeClient,
    checkpoints: CheckpointClient,
    checkpoint_payload: bytes,
    *,
    expected_version: int,
    prompt: str,
    response_schema: dict[str, Any] | None = None,
    suspension_id: UUID | None = None,
) -> NoReturn:
    """Commit a stable suspension saga and terminate the current activation."""
    unsafe = any(ord(char) < 32 and char not in "\n\t" for char in prompt)
    if not 1 <= len(prompt) <= 4096 or unsafe:
        raise ValueError("input prompt must be UI-safe and contain 1 to 4096 characters")
    suspension_id = suspension_id or uuid4()
    checkpoint_id = uuid5(NAMESPACE_URL, f"porfirium:checkpoint:{suspension_id}")
    input_request_id = uuid5(NAMESPACE_URL, f"porfirium:suspension:{suspension_id}")
    await checkpoints.put(
        checkpoint_payload,
        expected_version=expected_version,
        checkpoint_id=checkpoint_id,
        idempotency_key=f"suspension:{suspension_id}:checkpoint",
    )
    schema = Struct()
    schema.update(response_schema or {})
    await runtime.send(
        input_request_proposed=pb.InputRequestProposed(
            suspension_id=str(suspension_id), checkpoint_id=str(checkpoint_id),
            prompt=prompt, response_schema=schema,
        )
    )
    await runtime.send(
        suspension_committed=pb.SuspensionCommitted(
            suspension_id=str(suspension_id), checkpoint_id=str(checkpoint_id),
            input_request_id=str(input_request_id),
        )
    )
    raise InputSuspended(suspension_id, input_request_id)
