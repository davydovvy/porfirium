from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg


def _count(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])


async def prune(pool: Any, *, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.now(UTC)
    async with pool.acquire() as connection, connection.transaction():
        chunks = await connection.execute(
            """DELETE FROM message_chunks c USING messages m
               WHERE c.message_id=m.message_id
                 AND m.status IN ('completed','interrupted','failed')
                 AND m.completed_at IS NOT NULL AND m.completed_at < $1""",
            current - timedelta(minutes=30),
        )
        outbox = await connection.execute(
            "DELETE FROM outbox_events WHERE published_at IS NOT NULL AND published_at < $1",
            current - timedelta(days=91),
        )
        inbox = await connection.execute(
            "DELETE FROM inbox_events WHERE processed_at < $1",
            current - timedelta(days=31),
        )
    return {
        "message_chunks": _count(chunks),
        "published_outbox": _count(outbox),
        "inbox": _count(inbox),
    }


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        print(await prune(pool))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
