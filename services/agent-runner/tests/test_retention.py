import asyncio
from datetime import UTC, datetime

from agent_runner.retention import prune


class Database:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def acquire(self) -> "Database":
        return self

    def transaction(self) -> "Database":
        return self

    async def __aenter__(self) -> "Database":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, query: str, cutoff: datetime) -> str:
        self.queries.append(query)
        assert cutoff.tzinfo is UTC
        return "DELETE 2"


def test_retention_prunes_only_transport_and_replayed_failure_state() -> None:
    database = Database()
    result = asyncio.run(prune(database, now=datetime(2026, 9, 7, tzinfo=UTC)))
    assert set(result) == {
        "published_outbox", "phase2_inbox", "run_event_inbox", "replayed_dead_letters"
    }
    sql = " ".join(database.queries)
    assert "published_at IS NOT NULL" in sql
    assert "replayed_at IS NOT NULL" in sql
    assert "DELETE FROM runs" not in sql
    assert "runner_operator_audit" not in sql
