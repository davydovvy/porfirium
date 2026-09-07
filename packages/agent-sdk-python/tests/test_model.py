from uuid import UUID

import pytest
from google.protobuf.struct_pb2 import Struct

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
async def test_model_call_uses_runtime_channel_and_returns_typed_result() -> None:
    run_id = UUID("10000000-0000-0000-0000-000000000001")
    attempt_id = UUID("20000000-0000-0000-0000-000000000002")
    request_id = UUID("30000000-0000-0000-0000-000000000003")
    usage = Struct()
    usage.update({"output_tokens": 2})
    call = Call([
        pb.PlatformFrame(
            model_result=pb.ModelResult(
                request_id=str(request_id), content_utf8=b"hello", finish_reason="completed",
                usage=usage,
            )
        ),
        pb.PlatformFrame(acknowledgement=pb.Acknowledgement(accepted_sequence=1)),
    ])
    runtime = RuntimeClient(
        "unused", run_id=run_id, attempt_id=attempt_id, lease_epoch=1,
        run_capability="capability",
    )
    runtime._call = call

    result = await runtime.model("hi", request_id=request_id, max_output_tokens=32)

    assert result.content == "hello"
    assert result.usage == {"output_tokens": 2.0}
    assert call.writes[0].model_call.model == "default"
    assert call.writes[0].model_call.prompt == "hi"


@pytest.mark.asyncio
async def test_model_call_enforces_prompt_bounds_before_transport() -> None:
    runtime = RuntimeClient(
        "unused", run_id=UUID(int=1), attempt_id=UUID(int=2), lease_epoch=1,
        run_capability="capability",
    )
    with pytest.raises(ValueError, match="bounds"):
        await runtime.model("x" * (12 * 1024 + 1))
