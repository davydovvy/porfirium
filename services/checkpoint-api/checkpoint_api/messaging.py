from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any


def encode_payload(payload: Any) -> bytes:
    if isinstance(payload, str):
        return payload.encode()
    return json.dumps(payload, separators=(",", ":")).encode()


async def publish_pending(pool: Any, jetstream: Any) -> int:
    rows = await pool.fetch(
        "SELECT event_id,subject,payload FROM outbox_events WHERE published_at IS NULL "
        "AND available_at<=now() ORDER BY created_at LIMIT 100"
    )
    count = 0
    for row in rows:
        event_id = str(row["event_id"])
        await jetstream.publish(
            row["subject"], encode_payload(row["payload"]),
            headers={"Nats-Msg-Id": event_id, "Event-Id": event_id},
        )
        result = await pool.execute(
            "UPDATE outbox_events SET published_at=now(),publish_attempts=publish_attempts+1 "
            "WHERE event_id=$1 AND published_at IS NULL", row["event_id"]
        )
        count += result == "UPDATE 1"
    return count


async def publish_loop(pool: Any, jetstream: Any) -> None:
    while True:
        with suppress(Exception):
            await publish_pending(pool, jetstream)
        await asyncio.sleep(0.05)
