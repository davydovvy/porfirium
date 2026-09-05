from __future__ import annotations

from uuid import UUID

import asyncpg


async def apply_schedule_once(
    pool: asyncpg.Pool,
    *,
    event_id: UUID,
    run_id: UUID,
) -> bool:
    async with pool.acquire() as connection, connection.transaction():
        inserted = await connection.fetchval(
            """
            INSERT INTO inbox_events (event_id, handler)
            VALUES ($1, 'run-scheduler')
            ON CONFLICT (event_id, handler) DO NOTHING
            RETURNING event_id
            """,
            event_id,
        )
        if inserted is None:
            return False
        await connection.execute(
            "INSERT INTO schedule_effects (event_id, run_id) VALUES ($1, $2)",
            event_id,
            run_id,
        )
        return True
