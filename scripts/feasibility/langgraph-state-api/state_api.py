#!/usr/bin/env python3
"""Minimal HTTP checkpoint owner used only by the LangGraph feasibility gate."""

from __future__ import annotations

import argparse
import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_id TEXT,
    checkpoint_type TEXT NOT NULL,
    checkpoint_data TEXT NOT NULL,
    metadata_type TEXT NOT NULL,
    metadata_data TEXT NOT NULL,
    created_at INTEGER PRIMARY KEY AUTOINCREMENT,
    UNIQUE (thread_id, namespace, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS writes (
    thread_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    write_index INTEGER NOT NULL,
    channel TEXT NOT NULL,
    value_type TEXT NOT NULL,
    value_data TEXT NOT NULL,
    PRIMARY KEY (thread_id, namespace, checkpoint_id, task_id, write_index)
);
"""


class StateApi(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], database: Path) -> None:
        super().__init__(address, Handler)
        self.database = database
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection


class Handler(BaseHTTPRequestHandler):
    server: StateApi

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_048_576:
            raise ValueError("request exceeds checkpoint gate limit")
        return json.loads(self.rfile.read(length))

    def _reply(self, status: HTTPStatus, payload: Any = None) -> None:
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health/live":
            self._reply(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path != "/v1/checkpoints":
            self._reply(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        thread_id = query["thread_id"][0]
        namespace = query.get("namespace", [""])[0]
        checkpoint_id = query.get("checkpoint_id", [None])[0]
        limit = min(int(query.get("limit", ["100"])[0]), 100)
        where = "thread_id = ? AND namespace = ?"
        values: list[Any] = [thread_id, namespace]
        if checkpoint_id:
            where += " AND checkpoint_id = ?"
            values.append(checkpoint_id)
        with self.server.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM checkpoints WHERE {where} ORDER BY created_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                writes = connection.execute(
                    """
                    SELECT task_id, channel, value_type, value_data
                    FROM writes
                    WHERE thread_id = ? AND namespace = ? AND checkpoint_id = ?
                    ORDER BY task_id, write_index
                    """,
                    (thread_id, namespace, row["checkpoint_id"]),
                ).fetchall()
                item["writes"] = [dict(write) for write in writes]
                result.append(item)
        self._reply(HTTPStatus.OK, {"items": result})

    def do_PUT(self) -> None:
        if self.path == "/v1/checkpoints":
            payload = self._json()
            with self.server.connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO checkpoints (
                        thread_id, namespace, checkpoint_id, parent_id,
                        checkpoint_type, checkpoint_data, metadata_type, metadata_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["thread_id"],
                        payload["namespace"],
                        payload["checkpoint_id"],
                        payload.get("parent_id"),
                        payload["checkpoint_type"],
                        payload["checkpoint_data"],
                        payload["metadata_type"],
                        payload["metadata_data"],
                    ),
                )
            self._reply(HTTPStatus.OK, {"checkpoint_id": payload["checkpoint_id"]})
            return
        if self.path == "/v1/checkpoint-writes":
            payload = self._json()
            with self.server.connect() as connection:
                for index, write in enumerate(payload["writes"]):
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO writes (
                            thread_id, namespace, checkpoint_id, task_id,
                            write_index, channel, value_type, value_data
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            payload["thread_id"],
                            payload["namespace"],
                            payload["checkpoint_id"],
                            payload["task_id"],
                            index,
                            write["channel"],
                            write["value_type"],
                            write["value_data"],
                        ),
                    )
            self._reply(HTTPStatus.NO_CONTENT)
            return
        self._reply(HTTPStatus.NOT_FOUND)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    StateApi(("127.0.0.1", args.port), args.database).serve_forever()


if __name__ == "__main__":
    main()
