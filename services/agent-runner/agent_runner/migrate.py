from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

MIGRATIONS = Path(__file__).parents[1] / "migrations"


async def apply_migrations() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(742731906)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS runner_schema_migrations "
                "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = {
                row["version"]
                for row in await connection.fetch("SELECT version FROM runner_schema_migrations")
            }
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                if migration.name not in applied:
                    await connection.execute(migration.read_text())
                    await connection.execute(
                        "INSERT INTO runner_schema_migrations(version) VALUES($1)", migration.name
                    )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(apply_migrations())

