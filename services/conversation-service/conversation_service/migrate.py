from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg


async def migrate() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        directory = Path(__file__).resolve().parent.parent / "migrations"
        for path in sorted(directory.glob("*.sql")):
            if await connection.fetchval(
                "SELECT 1 FROM schema_migrations WHERE name=$1", path.name
            ):
                continue
            async with connection.transaction():
                await connection.execute(path.read_text())
                await connection.execute(
                    "INSERT INTO schema_migrations(name) VALUES($1)", path.name
                )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(migrate())
