from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import asyncpg
from nats.js import JetStreamContext


def encode_payload(payload: Any) -> bytes:
    if isinstance(payload, str):
        return payload.encode()
    return json.dumps(payload, separators=(",", ":")).encode()


async def enqueue(
    connection: asyncpg.Connection,
    *,
    event_id: UUID,
    subject: str,
    payload: Mapping[str, Any],
) -> None:
    await connection.execute(
        """
        INSERT INTO outbox_events (event_id, subject, payload)
        VALUES ($1, $2, $3::jsonb)
        ON CONFLICT (event_id) DO NOTHING
        """,
        event_id,
        subject,
        json.dumps(payload, separators=(",", ":")),
    )


async def publish_pending(pool: asyncpg.Pool, jetstream: JetStreamContext) -> int:
    rows = await pool.fetch(
        """
        SELECT event_id, subject, payload
        FROM outbox_events
        WHERE published_at IS NULL AND available_at <= now()
        ORDER BY created_at, event_id
        """
    )
    published = 0
    for row in rows:
        event_id = str(row["event_id"])
        payload = encode_payload(row["payload"])
        await jetstream.publish(
            row["subject"],
            payload,
            headers={"Nats-Msg-Id": event_id, "Event-Id": event_id},
        )
        result = await pool.execute(
            """
            UPDATE outbox_events
            SET published_at = now(), publish_attempts = publish_attempts + 1
            WHERE event_id = $1 AND published_at IS NULL
            """,
            row["event_id"],
        )
        published += result == "UPDATE 1"
    return published
