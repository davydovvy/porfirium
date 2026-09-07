from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["user_message", "user_response", "resume"]
    id: UUID


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger_type: Literal["user_message", "user_response", "resume"]
    trigger_id: UUID
    value: Any


class RunAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    user_id: UUID
    conversation_id: UUID
    thread_id: UUID
    release_id: UUID
    delegation_grant_id: UUID
    configuration_revision_id: UUID | None = None
    starting_checkpoint_id: UUID | None = None
    trigger: Trigger
    run_input: RunInput | None = None
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")

    def resolution_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("trigger")
        payload.pop("run_input")
        return payload


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    state: str
    active_attempt_id: UUID | None = None
    lease_epoch: int
    terminal_code: str | None = None
    created_at: datetime
    updated_at: datetime


class SignedSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specification_id: UUID
    run_id: UUID
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str
    key_id: str
