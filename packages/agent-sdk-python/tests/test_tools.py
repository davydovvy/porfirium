from uuid import UUID

import pytest
from google.protobuf.json_format import ParseDict

from porfirium_agent_sdk.proto import runtime_pb2 as pb
from porfirium_agent_sdk.runtime import RuntimeClient


class Call:
    def __init__(self, responses: list[pb.PlatformFrame]) -> None:
        self.responses = responses
        self.writes: list[pb.AgentFrame] = []

    async def write(self, frame: pb.AgentFrame) -> None:
        self.writes.append(frame)

    async def read(self) -> pb.PlatformFrame:
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_tool_call_uses_stable_identity_and_returns_typed_result() -> None:
    invocation_id = UUID("30000000-0000-0000-0000-000000000003")
    tool_result = pb.ToolResult(invocation_id=str(invocation_id))
    ParseDict({"zone": "UTC", "hour": 12}, tool_result.result)
    call = Call([
        pb.PlatformFrame(tool_result=tool_result),
        pb.PlatformFrame(acknowledgement=pb.Acknowledgement(accepted_sequence=1)),
    ])
    runtime = RuntimeClient(
        "unused", run_id=UUID(int=1), attempt_id=UUID(int=2), lease_epoch=1,
        run_capability="capability",
    )
    runtime._call = call

    result = await runtime.tool("time.current", {"zone": "UTC"}, invocation_id=invocation_id)

    assert result.result == {"zone": "UTC", "hour": 12.0}
    assert result.is_error is False
    assert call.writes[0].identity.idempotency_key == str(invocation_id)
    assert call.writes[0].tool_call.tool == "time.current"


@pytest.mark.asyncio
async def test_tool_call_enforces_argument_bounds_before_transport() -> None:
    runtime = RuntimeClient(
        "unused", run_id=UUID(int=1), attempt_id=UUID(int=2), lease_epoch=1,
        run_capability="capability",
    )
    with pytest.raises(ValueError, match="arguments"):
        await runtime.tool("time.current", {"value": "x" * (8 * 1024 + 1)})
