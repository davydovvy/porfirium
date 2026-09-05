"""LangGraph checkpointer that has HTTP access only."""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence
from typing import Any

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)


class HttpCheckpointer(BaseCheckpointSaver[int]):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _identity(config: dict[str, Any]) -> tuple[str, str, str | None]:
        values = config["configurable"]
        return values["thread_id"], values.get("checkpoint_ns", ""), values.get("checkpoint_id")

    def _request(
        self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
            return json.loads(body) if body else {}

    def _dump(self, value: Any) -> tuple[str, str]:
        value_type, data = self.serde.dumps_typed(value)
        return value_type, base64.b64encode(data).decode()

    def _load(self, value_type: str, data: str) -> Any:
        return self.serde.loads_typed((value_type, base64.b64decode(data)))

    def _tuple(self, item: dict[str, Any]) -> CheckpointTuple:
        config = {
            "configurable": {
                "thread_id": item["thread_id"],
                "checkpoint_ns": item["namespace"],
                "checkpoint_id": item["checkpoint_id"],
            }
        }
        parent_config = None
        if item["parent_id"]:
            parent_config = {
                "configurable": {
                    "thread_id": item["thread_id"],
                    "checkpoint_ns": item["namespace"],
                    "checkpoint_id": item["parent_id"],
                }
            }
        pending_writes = [
            (
                write["task_id"],
                write["channel"],
                self._load(write["value_type"], write["value_data"]),
            )
            for write in item["writes"]
        ]
        return CheckpointTuple(
            config,
            self._load(item["checkpoint_type"], item["checkpoint_data"]),
            self._load(item["metadata_type"], item["metadata_data"]),
            parent_config,
            pending_writes,
        )

    def get_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        thread_id, namespace, checkpoint_id = self._identity(config)
        query: dict[str, str | int] = {"thread_id": thread_id, "namespace": namespace, "limit": 1}
        if checkpoint_id:
            query["checkpoint_id"] = checkpoint_id
        items = self._request(f"/v1/checkpoints?{urllib.parse.urlencode(query)}")["items"]
        return self._tuple(items[0]) if items else None

    def list(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None or filter or before:
            raise NotImplementedError("the feasibility gate lists one thread without filters")
        thread_id, namespace, _ = self._identity(config)
        query = urllib.parse.urlencode(
            {"thread_id": thread_id, "namespace": namespace, "limit": limit or 100}
        )
        for item in self._request(f"/v1/checkpoints?{query}")["items"]:
            yield self._tuple(item)

    def put(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        del new_versions
        thread_id, namespace, parent_id = self._identity(config)
        checkpoint_type, checkpoint_data = self._dump(checkpoint)
        metadata_type, metadata_data = self._dump(metadata)
        self._request(
            "/v1/checkpoints",
            method="PUT",
            payload={
                "thread_id": thread_id,
                "namespace": namespace,
                "checkpoint_id": checkpoint["id"],
                "parent_id": parent_id,
                "checkpoint_type": checkpoint_type,
                "checkpoint_data": checkpoint_data,
                "metadata_type": metadata_type,
                "metadata_data": metadata_data,
            },
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        del task_path
        thread_id, namespace, checkpoint_id = self._identity(config)
        if checkpoint_id is None:
            raise ValueError("checkpoint_id is required for pending writes")
        serialized = []
        for channel, value in writes:
            value_type, value_data = self._dump(value)
            serialized.append(
                {"channel": channel, "value_type": value_type, "value_data": value_data}
            )
        self._request(
            "/v1/checkpoint-writes",
            method="PUT",
            payload={
                "thread_id": thread_id,
                "namespace": namespace,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "writes": serialized,
            },
        )
