import asyncio
from datetime import UTC, datetime

from agent_runtime_api.retention import prune


class Database:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def acquire(self) -> "Database": return self
    def transaction(self) -> "Database": return self
    async def __aenter__(self) -> "Database": return self
    async def __aexit__(self, *args: object) -> None: return None

    async def execute(self, query: str, cutoff: datetime) -> str:
        self.queries.append(query)
        return "DELETE 4"


def test_retention_removes_expired_attempt_buffers_in_dependency_order() -> None:
    database = Database()
    result = asyncio.run(prune(database, now=datetime(2026, 9, 7, tzinfo=UTC)))
    assert result == {"accepted_frames": 4, "runtime_attempts": 4, "published_outbox": 4}
    assert "accepted_frames" in database.queries[0]
    assert "runtime_attempts" in database.queries[1]
    assert "published_at IS NOT NULL" in database.queries[2]
