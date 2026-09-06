from uuid import UUID

import pytest

from porfirium_agent_sdk.suspension import InputSuspended, request_input


class Checkpoints:
    calls: list[dict]

    def __init__(self) -> None:
        self.calls = []

    async def put(self, payload: bytes, **kwargs):
        self.calls.append({"payload": payload, **kwargs})


class Runtime:
    frames: list[dict]

    def __init__(self) -> None:
        self.frames = []

    async def send(self, **payload):
        self.frames.append(payload)


@pytest.mark.asyncio
async def test_request_input_is_stable_and_ends_activation() -> None:
    suspension_id = UUID("10000000-0000-0000-0000-000000000001")
    runtime, checkpoints = Runtime(), Checkpoints()
    with pytest.raises(InputSuspended) as raised:
        await request_input(
            runtime, checkpoints, b"state", expected_version=2, prompt="Approve?",
            response_schema={"type": "boolean"}, suspension_id=suspension_id,
        )
    assert raised.value.suspension_id == suspension_id
    assert checkpoints.calls[0]["idempotency_key"] == f"suspension:{suspension_id}:checkpoint"
    proposed = runtime.frames[0]["input_request_proposed"]
    committed = runtime.frames[1]["suspension_committed"]
    assert proposed.checkpoint_id == committed.checkpoint_id
    assert committed.input_request_id == str(raised.value.input_request_id)
