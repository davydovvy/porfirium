import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

import live_tool_acceptance as acceptance


@pytest.fixture
def completion(monkeypatch):
    run_id = uuid4()
    completed = {
        "state": "completed",
        "terminal_code": None,
        "messages_confirmed": True,
        "reconciled_at": "2026-09-08",
        "completed_events": 1,
    }
    message = {
        "role": "assistant",
        "run_id": str(run_id),
        "status": "completed",
        "content": "hello",
    }

    class Connection:
        rows = [completed]
        closed = False
        reads = 0

        async def fetchrow(self, query, value):
            assert value == run_id
            self.reads += 1
            return self.rows.pop(0)

        async def close(self):
            self.closed = True

    connection = Connection()

    async def connect(*args, **kwargs):
        return connection

    async def sleep(*args):
        return None

    monkeypatch.setattr(acceptance.asyncpg, "connect", connect)
    monkeypatch.setattr(acceptance.asyncio, "sleep", sleep)
    monkeypatch.setattr(acceptance, "request", lambda *a, **k: {"messages": [message]})

    def verify():
        asyncio.run(
            acceptance.wait_for_completion(
                "unused",
                "http://bff",
                "token",
                run_id,
                "conversation",
                acceptance.Scenario("model-only", "1.0.1", "hello", ()),
            )
        )

    return connection, completed, message, verify


def test_completed_message_waits_for_durable_runner_completion(completion):
    connection, completed, _, verify = completion
    connection.rows = [None, {"state": "running"}, completed]
    verify()
    assert connection.reads == 3
    assert connection.closed


@pytest.mark.parametrize(
    "state,code",
    [
        ("failed", "attempt_retry_exhausted"),
        ("cancelled", "cancelled"),
    ],
)
def test_terminal_run_fails_immediately_without_assistant_message(
    completion, monkeypatch, state, code
):
    connection, _, _, verify = completion
    connection.rows = [{"state": state, "terminal_code": code}]
    monkeypatch.setattr(
        acceptance, "request", lambda *a, **k: pytest.fail("must fail before polling")
    )
    with pytest.raises(RuntimeError, match=code):
        verify()
    assert connection.reads == 1
    assert connection.closed


@pytest.mark.parametrize(
    "field,value",
    [
        ("messages_confirmed", False),
        ("reconciled_at", None),
        ("completed_events", 0),
        ("completed_events", 2),
    ],
)
def test_rejects_incomplete_or_duplicate_completion_evidence(completion, field, value):
    connection, completed, _, verify = completion
    completed[field] = value
    with pytest.raises(RuntimeError, match="invalid completion evidence"):
        verify()
    assert connection.closed


def test_rejects_empty_completed_message(completion):
    _, _, message, verify = completion
    message["content"] = " "
    with pytest.raises(RuntimeError, match="empty output"):
        verify()


def test_message_from_another_run_cannot_satisfy_acceptance(completion, monkeypatch):
    connection, completed, message, verify = completion
    message["run_id"] = str(uuid4())
    connection.rows = [completed]
    times = iter([0, 1, 301])
    monkeypatch.setattr(acceptance, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(RuntimeError, match="did not complete within 300 seconds"):
        verify()
    assert connection.closed
