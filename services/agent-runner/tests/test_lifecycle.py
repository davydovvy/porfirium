from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from agent_runner.service import RunnerService


class CancellationConnection:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.run = {
            "run_id": uuid4(),
            "state": "running",
            "active_attempt_id": uuid4(),
            "lease_epoch": 3,
            "terminal_code": None,
            "created_at": now,
            "updated_at": now,
            "user_id": uuid4(),
            "conversation_id": uuid4(),
            "thread_id": uuid4(),
            "trace_id": uuid4().hex,
        }
        self.attempt = {
            "attempt_id": self.run["active_attempt_id"],
            "container_id": "container-exact",
            "network_name": f"porfirium-attempt-{self.run['active_attempt_id']}",
            "active_message_id": uuid4(),
        }
        self.events: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def transaction(self):
        return self

    async def fetchrow(self, query, *args):
        if "FROM attempts" in query:
            return self.attempt
        if "FROM runs" in query:
            return self.run
        raise AssertionError(query)

    async def execute(self, query, *args):
        if "SET state='cancelling'" in query:
            self.run["state"] = "cancelling"
        elif "SET state='cancelled'" in query:
            self.run.update(state="cancelled", terminal_code="cancelled", active_attempt_id=None)
        elif "INSERT INTO outbox_events" in query:
            self.events.append(json.loads(args[2]))
        return "UPDATE 1"


class CancellationPool:
    def __init__(self, connection: CancellationConnection) -> None:
        self.connection = connection

    def acquire(self):
        return self.connection


class CancellationBackend:
    def __init__(self) -> None:
        self.removed: list[tuple[str | None, str]] = []

    async def remove(self, container_id: str | None, network_name: str) -> None:
        self.removed.append((container_id, network_name))


def test_cancellation_interrupts_visible_output_and_emits_one_terminal_event() -> None:
    asyncio.run(_verify_cancellation())


async def _verify_cancellation() -> None:
    connection = CancellationConnection()
    backend = CancellationBackend()
    service = RunnerService(
        CancellationPool(connection),
        backend,
        capability_secret="test-secret",
        runtime_url="runtime:50051",
    )

    first = await service.cancel(connection.run["run_id"], "cancel-operation")
    replay = await service.cancel(connection.run["run_id"], "cancel-operation")

    assert first.state == replay.state == "cancelled"
    assert first.terminal_code == replay.terminal_code == "cancelled"
    assert backend.removed == [
        (connection.attempt["container_id"], connection.attempt["network_name"])
    ]
    assert len(connection.events) == 2
    interruption, terminal = connection.events
    assert interruption["type"] == "porfirium.message.interrupted.v1"
    assert interruption["data"] == {
        "message_id": str(connection.attempt["active_message_id"]),
        "code": "cancelled",
    }
    assert terminal["type"] == "porfirium.run.cancelled.v1"
    assert terminal["data"] == {
        "run_id": str(connection.run["run_id"]),
        "state": "cancelled",
        "attempt_id": str(connection.attempt["attempt_id"]),
        "lease_epoch": 3,
        "code": "cancelled",
    }
    assert sum(event["type"] == "porfirium.run.cancelled.v1" for event in connection.events) == 1
