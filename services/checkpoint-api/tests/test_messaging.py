from checkpoint_api.messaging import encode_payload


def test_encode_payload_preserves_asyncpg_json_text() -> None:
    assert encode_payload('{"event":"checkpoint"}') == b'{"event":"checkpoint"}'


def test_encode_payload_serializes_decoded_json() -> None:
    assert encode_payload({"event": "checkpoint"}) == b'{"event":"checkpoint"}'
