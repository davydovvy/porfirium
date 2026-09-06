import asyncio
import os
from pathlib import Path

import asyncpg


async def migrate() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        for path in sorted((Path(__file__).parent.parent / "migrations").glob("*.sql")):
            await connection.execute(path.read_text())
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(migrate())
