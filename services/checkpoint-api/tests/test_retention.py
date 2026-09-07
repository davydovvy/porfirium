import asyncio
from datetime import UTC, datetime

from checkpoint_api.retention import prune


class Database:
    def acquire(self) -> "Database": return self
    def transaction(self) -> "Database": return self
    async def __aenter__(self) -> "Database": return self
    async def __aexit__(self, *args: object) -> None: return None

    async def execute(self, query: str, cutoff: datetime) -> str:
        assert "published_at IS NOT NULL" in query
        assert "checkpoints" not in query
        return "DELETE 5"


def test_retention_never_deletes_checkpoint_business_state() -> None:
    assert asyncio.run(prune(Database(), now=datetime(2026, 9, 7, tzinfo=UTC))) == {
        "published_outbox": 5
    }
