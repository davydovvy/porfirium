from datetime import UTC, datetime, timedelta

from agent_runner.service import _retry_allowed


def test_retry_is_bounded_by_attempt_count() -> None:
    deadline = datetime.now(UTC) + timedelta(minutes=1)

    assert _retry_allowed(2, deadline, 3)
    assert not _retry_allowed(3, deadline, 3)


def test_retry_stops_after_run_deadline() -> None:
    deadline = datetime.now(UTC) - timedelta(seconds=1)

    assert not _retry_allowed(1, deadline, 3)
