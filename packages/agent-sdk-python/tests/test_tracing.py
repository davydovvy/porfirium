from uuid import UUID

from porfirium_agent_sdk import RuntimeClient


def test_frame_identity_carries_signed_run_trace_with_fresh_span() -> None:
    runtime = RuntimeClient(
        "runtime:50051",
        run_id=UUID("10000000-0000-0000-0000-000000000001"),
        attempt_id=UUID("20000000-0000-0000-0000-000000000002"),
        lease_epoch=1,
        run_capability="capability",
        trace_id="3" * 32,
    )

    first = runtime._identity(1)
    second = runtime._identity(2)

    assert first.traceparent.startswith(f"00-{'3' * 32}-")
    assert first.traceparent.endswith("-01")
    assert first.traceparent != second.traceparent
