from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from porfirium_agent_sdk.checkpoints import CheckpointClient


class LangGraphCheckpointer:
    """Async LangGraph checkpointer backed only by the Checkpoint API."""

    def __init__(self, client: CheckpointClient) -> None:
        self.client = client

    async def aget_tuple(self, config: dict[str, Any]) -> dict[str, Any] | None:
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if checkpoint_id is None:
            entries = await self.client.list()
            if not entries:
                return None
            checkpoint_id = entries[0].checkpoint_id
        value = await self.client.get_json(UUID(str(checkpoint_id)))
        return {"config": config, **value}

    async def alist(
        self,
        config: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        del config
        entries = await self.client.list()
        for entry in entries[:limit]:
            yield {
                "config": {
                    "configurable": {
                        "thread_id": str(entry.thread_id),
                        "checkpoint_id": str(entry.checkpoint_id),
                    }
                },
                "metadata": {"version": entry.version},
            }

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        expected_version = int(config.get("configurable", {}).get("checkpoint_version", 0))
        item = await self.client.put_json(
            {"checkpoint": checkpoint, "metadata": metadata, "new_versions": new_versions or {}},
            expected_version=expected_version,
        )
        return {
            "configurable": {
                "thread_id": str(item.thread_id),
                "checkpoint_id": str(item.checkpoint_id),
                "checkpoint_version": item.version,
            }
        }
