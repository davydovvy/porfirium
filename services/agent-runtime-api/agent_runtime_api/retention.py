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
        frames = await connection.execute(
            """DELETE FROM accepted_frames f USING runtime_attempts a
               WHERE f.run_id=a.run_id AND f.attempt_id=a.attempt_id
                 AND f.lease_epoch=a.lease_epoch AND a.deadline < $1""",
            current - timedelta(days=1),
        )
        attempts = await connection.execute(
            "DELETE FROM runtime_attempts WHERE deadline < $1",
            current - timedelta(days=1),
        )
        outbox = await connection.execute(
            "DELETE FROM outbox_events WHERE published_at IS NOT NULL AND published_at < $1",
            current - timedelta(days=31),
        )
    return {
        "accepted_frames": _count(frames),
        "runtime_attempts": _count(attempts),
        "published_outbox": _count(outbox),
    }


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        print(await prune(pool))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
