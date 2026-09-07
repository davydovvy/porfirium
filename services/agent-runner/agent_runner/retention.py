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
        outbox = await connection.execute(
            "DELETE FROM outbox_events WHERE published_at IS NOT NULL AND published_at < $1",
            current - timedelta(days=31),
        )
        phase2_inbox = await connection.execute(
            "DELETE FROM inbox_events WHERE processed_at < $1",
            current - timedelta(days=8),
        )
        run_inbox = await connection.execute(
            "DELETE FROM run_event_inbox WHERE received_at < $1",
            current - timedelta(days=31),
        )
        dead_letters = await connection.execute(
            "DELETE FROM runner_dead_letters WHERE replayed_at IS NOT NULL AND replayed_at < $1",
            current - timedelta(days=31),
        )
    return {
        "published_outbox": _count(outbox),
        "phase2_inbox": _count(phase2_inbox),
        "run_event_inbox": _count(run_inbox),
        "replayed_dead_letters": _count(dead_letters),
    }


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        print(await prune(pool))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
