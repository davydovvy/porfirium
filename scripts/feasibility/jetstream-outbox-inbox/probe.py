#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path

import nats
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.errors import FetchTimeoutError


def database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            event_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
            available_at REAL NOT NULL, published INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS inbox (event_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS effects (event_id TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dead_letters (
            event_id TEXT PRIMARY KEY, error_code TEXT NOT NULL
        );
        """
    )
    return connection


async def consume(
    subscription, connection: sqlite3.Connection, jetstream, *, replay: bool = False
) -> None:
    idle = 0
    while idle < 4:
        try:
            messages = await subscription.fetch(batch=10, timeout=0.25)
        except (FetchTimeoutError, NatsTimeoutError):
            idle += 1
            continue
        idle = 0
        for message in messages:
            try:
                payload = json.loads(message.data)
                if set(payload) != {"event_id", "value"} or not isinstance(payload["value"], str):
                    raise ValueError("invalid event schema")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                if replay:
                    await message.ack()
                elif message.metadata.num_delivered >= 3:
                    event_id = message.headers.get("Event-Id", "unknown")
                    connection.execute(
                        "INSERT OR IGNORE INTO dead_letters VALUES (?, ?)",
                        (event_id, "invalid_event_schema"),
                    )
                    connection.commit()
                    safe_dead_letter = json.dumps(
                        {"event_id": event_id, "error_code": "invalid_event_schema"}
                    ).encode()
                    await jetstream.publish("gate.dlq", safe_dead_letter)
                    await message.ack()
                else:
                    await message.nak(delay=0.1)
                continue
            try:
                with connection:
                    connection.execute("INSERT INTO inbox VALUES (?)", (payload["event_id"],))
                    connection.execute(
                        "INSERT INTO effects VALUES (?, ?)",
                        (payload["event_id"], payload["value"]),
                    )
            except sqlite3.IntegrityError:
                pass
            await message.ack()


async def run(args: argparse.Namespace) -> None:
    connection = database(args.database)
    now = time.time()
    delayed_at = now + 0.5
    rows = [
        ("normal", json.dumps({"event_id": "normal", "value": "one"}), now),
        ("delayed", json.dumps({"event_id": "delayed", "value": "later"}), delayed_at),
        ("poison", "not-json-and-must-not-enter-the-dlq", now),
    ]
    connection.executemany(
        "INSERT INTO outbox(event_id, payload, available_at) VALUES (?, ?, ?)", rows
    )
    connection.commit()

    client = await nats.connect(args.server)
    jetstream = client.jetstream()
    await jetstream.add_stream(name="GATE_EVENTS", subjects=["gate.events"])
    await jetstream.add_stream(name="GATE_DLQ", subjects=["gate.dlq"])
    subscription = await jetstream.pull_subscribe(
        "gate.events",
        durable="gate-worker",
        config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, max_deliver=3, ack_wait=0.2),
    )

    for event_id, payload, _ in connection.execute(
        "SELECT event_id, payload, available_at FROM outbox WHERE available_at <= ?", (time.time(),)
    ):
        await jetstream.publish(
            "gate.events", payload.encode(), headers={"Nats-Msg-Id": event_id, "Event-Id": event_id}
        )
        connection.execute("UPDATE outbox SET published = 1 WHERE event_id = ?", (event_id,))
    connection.commit()

    duplicate_payload = json.dumps({"event_id": "normal", "value": "one"}).encode()
    await jetstream.publish(
        "gate.events",
        duplicate_payload,
        headers={"Nats-Msg-Id": "forced-redelivery", "Event-Id": "normal"},
    )
    await asyncio.sleep(max(0, delayed_at - time.time()))
    delayed_payload = connection.execute(
        "SELECT payload FROM outbox WHERE event_id = 'delayed'"
    ).fetchone()[0]
    await jetstream.publish(
        "gate.events",
        delayed_payload.encode(),
        headers={"Nats-Msg-Id": "delayed", "Event-Id": "delayed"},
    )
    connection.execute("UPDATE outbox SET published = 1 WHERE event_id = 'delayed'")
    connection.commit()
    published_delayed_at = time.time()

    await consume(subscription, connection, jetstream)
    effect_count = connection.execute("SELECT count(*) FROM effects").fetchone()[0]
    assert effect_count == 2
    assert published_delayed_at >= delayed_at
    assert connection.execute("SELECT count(*) FROM dead_letters").fetchone()[0] == 1
    assert connection.execute("SELECT count(*) FROM outbox WHERE published = 1").fetchone()[0] == 3
    dlq_subscription = await jetstream.pull_subscribe("gate.dlq", durable="gate-dlq-review")
    dlq_messages = await dlq_subscription.fetch(batch=1, timeout=1)
    dead_letter_payload = json.loads(dlq_messages[0].data)
    assert dead_letter_payload == {"event_id": "poison", "error_code": "invalid_event_schema"}
    assert b"not-json-and-must-not-enter-the-dlq" not in dlq_messages[0].data
    await dlq_messages[0].ack()

    replay_subscription = await jetstream.pull_subscribe(
        "gate.events",
        durable="gate-replay",
        config=ConsumerConfig(
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL,
        ),
    )
    await consume(replay_subscription, connection, jetstream, replay=True)
    assert connection.execute("SELECT count(*) FROM effects").fetchone()[0] == effect_count
    dead_letter = connection.execute(
        "SELECT event_id, error_code FROM dead_letters"
    ).fetchone()
    assert dead_letter == ("poison", "invalid_event_schema")
    await client.close()
    connection.close()
    print("PASS: outbox published immediate and delayed events")
    print("PASS: duplicate delivery and full replay produced one effect per event")
    print("PASS: poison event retried three times and dead-lettered without its payload")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True, type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
