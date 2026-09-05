from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import nats
from nats.aio.client import Client as NatsClient
from nats.js.api import AckPolicy, ConsumerConfig

from agent_runner.inbox import apply_schedule_once
from agent_runner.outbox import enqueue, publish_pending

EVENT_ID = UUID("11e29722-bd91-4f1a-8c74-91ffc3b86bfc")
RUN_ID = UUID("0646af1f-e305-4ec0-a47e-cff026f41a42")
SUBJECT = "porfirium.run.command.schedule"
DURABLE = "phase2-run-scheduler"


def event_payload() -> dict[str, Any]:
    return {
        "specversion": "1.0",
        "type": "porfirium.run.command.schedule.v1",
        "id": str(EVENT_ID),
        "source": "agent-runner",
        "subject": f"run/{RUN_ID}",
        "time": "2026-09-05T10:15:30Z",
        "user_id": "c6d45c64-d9a7-4c31-ac4c-2e33e24c83ae",
        "conversation_id": "35d05b66-52ac-453c-bdf2-a5f720ed1372",
        "thread_id": "8bb476e5-67ae-45c3-8df7-9919b56d2c78",
        "run_id": str(RUN_ID),
        "correlation_id": "51167a9f-e2a1-4d07-90a6-d3ca19ec9a04",
        "causation_id": "b59bfbc5-024c-46a8-a6c6-76d226c60193",
        "traceparent": "00-51167a9fe2a14d0790a6d3ca19ec9a04-43f1670ab21c4f08-01",
        "schema_version": 1,
        "aggregate_sequence": 1,
        "data": {
            "run_id": str(RUN_ID),
            "action": "schedule",
            "idempotency_key": "schedule-0646af1f",
        },
    }


async def connect_nats() -> NatsClient:
    return await nats.connect(
        os.environ["NATS_URL"],
        user=os.environ["NATS_USER"],
        password=os.environ["NATS_PASSWORD"],
    )


async def migrate_and_publish(pool: asyncpg.Pool) -> None:
    migration = Path("migrations/0001_outbox_inbox.sql").read_text()
    await pool.execute(migration)
    async with pool.acquire() as connection, connection.transaction():
        await enqueue(
            connection,
            event_id=EVENT_ID,
            subject=SUBJECT,
            payload=event_payload(),
        )
    client = await connect_nats()
    try:
        assert await publish_pending(pool, client.jetstream()) == 1
    finally:
        await client.close()


async def consume(pool: asyncpg.Pool, *, acknowledge: bool) -> None:
    client = await connect_nats()
    try:
        subscription = await client.jetstream().pull_subscribe(
            SUBJECT,
            durable=DURABLE,
            config=ConsumerConfig(
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=1,
                max_deliver=5,
            ),
        )
        message = (await subscription.fetch(batch=1, timeout=5))[0]
        payload = json.loads(message.data)
        assert payload["id"] == str(EVENT_ID)
        assert payload["data"]["action"] == "schedule"
        await apply_schedule_once(pool, event_id=EVENT_ID, run_id=RUN_ID)
        if acknowledge:
            await message.ack_sync(timeout=2)
    finally:
        await client.close()


async def assert_state(pool: asyncpg.Pool) -> None:
    assert await pool.fetchval(
        "SELECT count(*) FROM outbox_events WHERE published_at IS NOT NULL"
    ) == 1
    assert await pool.fetchval("SELECT count(*) FROM inbox_events") == 1
    assert await pool.fetchval("SELECT count(*) FROM schedule_effects") == 1


async def run(command: str) -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        if command == "publish":
            await migrate_and_publish(pool)
        elif command == "consume-unacked":
            await consume(pool, acknowledge=False)
        elif command == "consume-ack":
            await consume(pool, acknowledge=True)
        else:
            await assert_state(pool)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("publish", "consume-unacked", "consume-ack", "assert"),
    )
    args = parser.parse_args()
    asyncio.run(run(args.command))


if __name__ == "__main__":
    main()
