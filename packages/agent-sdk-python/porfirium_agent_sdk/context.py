from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID

from porfirium_agent_sdk.checkpoints import CheckpointClient


@dataclass(frozen=True, slots=True)
class RunIdentity:
    user_id: UUID
    release_id: UUID
    conversation_id: UUID
    thread_id: UUID
    run_id: UUID
    attempt_id: UUID
    lease_epoch: int


class AgentContext:
    def __init__(
        self,
        *,
        identity: RunIdentity,
        deadline_epoch_seconds: float,
        configuration: Mapping[str, Any],
        checkpoints: CheckpointClient,
    ) -> None:
        self.identity = identity
        self.deadline_epoch_seconds = deadline_epoch_seconds
        self.configuration = MappingProxyType(dict(configuration))
        self.checkpoints = checkpoints

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_epoch_seconds - time.time())

    def ensure_active(self) -> None:
        if self.remaining_seconds <= 0:
            raise TimeoutError("run deadline exceeded")
