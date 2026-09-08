from uuid import UUID

import pytest
from test_model import Call

from porfirium_agent_sdk.proto import runtime_pb2 as pb
from porfirium_agent_sdk.runtime import RuntimeClient


@pytest.mark.asyncio
async def test_result_proposal_waits_for_durable_acknowledgement() -> None:
    runtime = RuntimeClient(
        "unused",
        run_id=UUID(int=1),
        attempt_id=UUID(int=2),
        lease_epoch=1,
        run_capability="capability",
    )
    call = Call([pb.PlatformFrame(acknowledgement=pb.Acknowledgement(accepted_sequence=1))])
    runtime._call = call
    await runtime.propose_result([UUID(int=3)], final_checkpoint_id=UUID(int=4))
    assert call.writes[0].result_proposed == pb.ResultProposed(
        final_message_ids=[str(UUID(int=3))],
        final_checkpoint_id=str(UUID(int=4)),
    )
    assert runtime._last_ack == 1
    assert runtime._pending == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("messages", [[UUID(int=1)] * 2, [UUID(int=i) for i in range(65)]])
async def test_result_proposal_rejects_duplicate_or_oversized_message_set(messages) -> None:
    runtime = RuntimeClient(
        "unused",
        run_id=UUID(int=1),
        attempt_id=UUID(int=2),
        lease_epoch=1,
        run_capability="capability",
    )
    with pytest.raises(ValueError, match="invalid final message IDs"):
        await runtime.propose_result(messages)
