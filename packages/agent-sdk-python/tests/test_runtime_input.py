from uuid import UUID

import pytest
from google.protobuf.json_format import ParseDict

from porfirium_agent_sdk.errors import PlatformError
from porfirium_agent_sdk.proto import runtime_pb2 as pb
from porfirium_agent_sdk.runtime import decode_run_input


def test_decodes_typed_user_message_input() -> None:
    trigger_id = UUID("10000000-0000-0000-0000-000000000001")
    value = pb.RunInput(trigger_type="user_message", trigger_id=str(trigger_id))
    ParseDict("hello", value.value)

    decoded = decode_run_input(value)

    assert decoded is not None
    assert decoded.trigger_type == "user_message"
    assert decoded.trigger_id == trigger_id
    assert decoded.value == "hello"
    assert decoded.starting_checkpoint_id is None


def test_rejects_invalid_input_identity() -> None:
    value = pb.RunInput(trigger_type="user_message", trigger_id="not-a-uuid")
    ParseDict("hello", value.value)

    with pytest.raises(PlatformError) as raised:
        decode_run_input(value)
    assert raised.value.code == "run_input_invalid"
