import asyncio
from datetime import UTC, datetime

from conversation_service.retention import prune


class Database:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def acquire(self) -> "Database": return self
    def transaction(self) -> "Database": return self
    async def __aenter__(self) -> "Database": return self
    async def __aexit__(self, *args: object) -> None: return None

    async def execute(self, query: str, cutoff: datetime) -> str:
        self.queries.append(query)
        return "DELETE 3"


def test_retention_preserves_canonical_messages_and_presentation_history() -> None:
    database = Database()
    result = asyncio.run(prune(database, now=datetime(2026, 9, 7, tzinfo=UTC)))
    assert result == {"message_chunks": 3, "published_outbox": 3, "inbox": 3}
    sql = " ".join(database.queries)
    assert "DELETE FROM message_chunks" in sql
    assert "DELETE FROM messages" not in sql
    assert "presentation_events" not in sql
    assert "request_idempotency" not in sql
