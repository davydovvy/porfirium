from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from conversation_service.problems import ConversationProblem

MAX_MESSAGE_BYTES = 256 * 1024
MAX_CHUNKS = 65_536


def now_utc() -> datetime:
    return datetime.now(UTC)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


@dataclass(slots=True)
class Conversation:
    conversation_id: UUID
    owner_id: UUID
    thread_id: UUID
    release_id: UUID
    title: str
    configuration_revision_id: UUID | None = None
    delegation_grant_id: UUID | None = None
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    last_sequence: int = 0


@dataclass(slots=True)
class Message:
    message_id: UUID
    conversation_id: UUID
    run_id: UUID
    role: str
    status: str
    content: str
    created_at: datetime = field(default_factory=now_utc)
    completed_at: datetime | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InputRequest:
    input_request_id: UUID
    conversation_id: UUID
    run_id: UUID
    suspension_id: UUID
    checkpoint_id: UUID
    prompt: str
    schema: dict[str, Any]
    delegation_grant_id: UUID | None = None
    state: str = "pending"
    response: Any = None
    response_run_id: UUID | None = None
    created_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class PresentationEvent:
    conversation_id: UUID
    sequence: int
    event_type: str
    data: dict[str, Any]
    created_at: datetime = field(default_factory=now_utc)


def validate_completion(data: dict[str, Any], chunks: dict[int, str]) -> str:
    try:
        content = str(data["content"])
        content_bytes = int(data["content_bytes"])
        chunk_count = int(data["chunk_count"])
        digest = str(data["content_sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversationProblem(
            422, "completion_invalid", "Completion metadata is invalid"
        ) from exc
    encoded = content.encode()
    if len(encoded) > MAX_MESSAGE_BYTES or not 0 <= chunk_count <= MAX_CHUNKS:
        raise ConversationProblem(422, "completion_invalid", "Completion bounds are invalid")
    if len(encoded) != content_bytes or hashlib.sha256(encoded).hexdigest() != digest:
        raise ConversationProblem(422, "completion_invalid", "Canonical content hash is invalid")
    if len(chunks) != chunk_count or sorted(chunks) != list(range(1, chunk_count + 1)):
        raise ConversationProblem(409, "completion_incomplete", "Message chunks are incomplete")
    if "".join(chunks[index] for index in range(1, chunk_count + 1)) != content:
        raise ConversationProblem(
            409, "completion_mismatch", "Canonical content differs from deltas"
        )
    return content


def message_json(message: Message) -> dict[str, Any]:
    return {
        "message_id": str(message.message_id),
        "run_id": str(message.run_id),
        "role": message.role,
        "status": message.status,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "completed_at": message.completed_at.isoformat() if message.completed_at else None,
        "finish_reason": message.finish_reason,
        "usage": message.usage,
    }


def input_json(item: InputRequest) -> dict[str, Any]:
    return {
        "input_request_id": str(item.input_request_id),
        "run_id": str(item.run_id),
        "prompt": item.prompt,
        "schema": item.schema,
        "state": item.state,
        "created_at": item.created_at.isoformat(),
    }


class MemoryStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.messages: dict[UUID, Message] = {}
        self.inputs: dict[UUID, InputRequest] = {}
        self.suspensions: dict[UUID, tuple[UUID, UUID, UUID]] = {}
        self.events: dict[UUID, list[PresentationEvent]] = {}
        self.chunks: dict[UUID, dict[int, str]] = {}
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, Any]] = {}
        self.inbox: set[UUID] = set()
        self.outbox: list[dict[str, Any]] = []

    def _owned(self, owner_id: UUID, conversation_id: UUID) -> Conversation:
        item = self.conversations.get(conversation_id)
        if item is None or item.owner_id != owner_id:
            raise ConversationProblem(404, "conversation_not_found", "Conversation was not found")
        return item

    def _event(self, item: Conversation, event_type: str, data: dict[str, Any]) -> int:
        item.last_sequence += 1
        item.updated_at = now_utc()
        self.events.setdefault(item.conversation_id, []).append(
            PresentationEvent(item.conversation_id, item.last_sequence, event_type, data)
        )
        return item.last_sequence

    async def create_conversation(
        self, owner_id: UUID, idempotency_key: str, payload: dict[str, Any]
    ) -> Conversation:
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        key = (owner_id, "create_conversation", idempotency_key)
        if key in self.idempotency:
            old_digest, conversation_id = self.idempotency[key]
            if old_digest != digest:
                raise ConversationProblem(409, "idempotency_conflict", "Idempotency key was reused")
            return self.conversations[conversation_id]
        item = Conversation(conversation_id=uuid4(), owner_id=owner_id, **payload)
        self.conversations[item.conversation_id] = item
        self.events[item.conversation_id] = []
        self.idempotency[key] = (digest, item.conversation_id)
        return item

    async def list_conversations(self, owner_id: UUID) -> list[Conversation]:
        return sorted(
            (item for item in self.conversations.values() if item.owner_id == owner_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    async def projection(self, owner_id: UUID, conversation_id: UUID) -> dict[str, Any]:
        item = self._owned(owner_id, conversation_id)
        return {
            "conversation": item,
            "messages": [m for m in self.messages.values() if m.conversation_id == conversation_id],
            "input_requests": [
                r for r in self.inputs.values() if r.conversation_id == conversation_id
            ],
        }

    async def create_message(
        self, owner_id: UUID, conversation_id: UUID, idempotency_key: str, payload: dict[str, Any]
    ) -> tuple[Message, int]:
        item = self._owned(owner_id, conversation_id)
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        key = (owner_id, f"message:{conversation_id}", idempotency_key)
        if key in self.idempotency:
            old_digest, result = self.idempotency[key]
            if old_digest != digest:
                raise ConversationProblem(409, "idempotency_conflict", "Idempotency key was reused")
            return self.messages[result[0]], result[1]
        message_id = payload["message_id"]
        if message_id in self.messages:
            raise ConversationProblem(409, "message_exists", "Message ID already exists")
        message = Message(
            message_id, conversation_id, payload["run_id"], "user", "completed", payload["content"]
        )
        self.messages[message_id] = message
        item.delegation_grant_id = payload["delegation_grant_id"]
        sequence = self._event(item, "message.completed", message_json(message))
        self.outbox.append(
            {
                "type": "porfirium.run.requested.v1",
                "user_id": str(owner_id),
                "conversation_id": str(conversation_id),
                "thread_id": str(item.thread_id),
                "release_id": str(item.release_id),
                "run_id": str(payload["run_id"]),
                "message_id": str(message_id),
                "delegation_grant_id": str(payload["delegation_grant_id"]),
            }
        )
        self.idempotency[key] = (digest, (message_id, sequence))
        return message, sequence

    async def replay(
        self, owner_id: UUID, conversation_id: UUID, after: int, limit: int = 1000
    ) -> list[PresentationEvent]:
        self._owned(owner_id, conversation_id)
        return [event for event in self.events[conversation_id] if event.sequence > after][:limit]

    def _streaming_message(self, message_id: UUID | None, conversation_id: UUID) -> Message:
        message = self.messages.get(message_id) if message_id else None
        if message is None or message.conversation_id != conversation_id:
            raise ConversationProblem(409, "message_not_started", "Message has not started")
        if message.status != "streaming":
            raise ConversationProblem(409, "message_terminal", "Message is already terminal")
        return message

    async def project(self, envelope: dict[str, Any]) -> int | None:
        try:
            event_id = UUID(str(envelope["id"]))
            conversation_id = UUID(str(envelope["conversation_id"]))
            owner_id = UUID(str(envelope["user_id"]))
            run_id = UUID(str(envelope["run_id"]))
            data = envelope["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationProblem(
                422, "event_invalid", "Runtime event envelope is invalid"
            ) from exc
        if event_id in self.inbox:
            return None
        if envelope.get("schema_version") != 1:
            raise ConversationProblem(422, "event_invalid", "Runtime event envelope is invalid")
        item = self._owned(owner_id, conversation_id)
        event_type = str(envelope.get("type"))
        message_id = UUID(str(data["message_id"])) if data.get("message_id") else None
        if event_type == "porfirium.message.started.v1":
            assert message_id is not None
            existing = self.messages.get(message_id)
            if existing is None:
                self.messages[message_id] = Message(
                    message_id, conversation_id, run_id, "assistant", "streaming", ""
                )
                self.chunks[message_id] = {}
            elif existing.run_id != run_id:
                raise ConversationProblem(409, "message_conflict", "Message identity conflicts")
        elif event_type == "porfirium.message.delta.v1":
            message = self._streaming_message(message_id, conversation_id)
            sequence = int(data.get("chunk_sequence", 0))
            content = str(data.get("content", ""))
            if sequence < 1 or not content or len(content.encode()) > 4096:
                raise ConversationProblem(422, "delta_invalid", "Message delta is invalid")
            previous = self.chunks[message.message_id].get(sequence)
            if previous is not None and previous != content:
                raise ConversationProblem(409, "delta_conflict", "Chunk sequence conflicts")
            self.chunks[message.message_id][sequence] = content
        elif event_type == "porfirium.message.completed.v1":
            message = self._streaming_message(message_id, conversation_id)
            message.content = validate_completion(data, self.chunks[message.message_id])
            message.status = "completed"
            message.completed_at = now_utc()
            message.finish_reason = str(data.get("finish_reason", "stop"))
            message.usage = data.get("usage") or {}
        elif event_type in {"porfirium.message.interrupted.v1", "porfirium.message.failed.v1"}:
            message = self._streaming_message(message_id, conversation_id)
            message.content = "".join(
                value for _, value in sorted(self.chunks[message.message_id].items())
            )
            message.status = "interrupted" if "interrupted" in event_type else "failed"
        elif event_type == "porfirium.input.request_proposed.v1":
            suspension_id = UUID(str(data["suspension_id"]))
            request_id = uuid5(NAMESPACE_URL, f"porfirium:suspension:{suspension_id}")
            self.inputs.setdefault(
                request_id,
                InputRequest(
                    request_id,
                    conversation_id,
                    run_id,
                    suspension_id,
                    UUID(str(data["checkpoint_id"])),
                    str(data["prompt"]),
                    data.get("response_schema") or data.get("schema") or {},
                    item.delegation_grant_id,
                    "reserved",
                ),
            )
            commitment = self.suspensions.get(suspension_id)
            if commitment:
                self._commit_input(self.inputs[request_id], commitment)
                self.inbox.add(event_id)
                return self._event(
                    item, "input.request_created", input_json(self.inputs[request_id])
                )
            self.inbox.add(event_id)
            return None
        elif event_type == "porfirium.run.suspension_committed.v1":
            suspension_id = UUID(str(data["suspension_id"]))
            commitment = (
                run_id, UUID(str(data["checkpoint_id"])), UUID(str(data["input_request_id"]))
            )
            self.suspensions.setdefault(suspension_id, commitment)
            request = next(
                (value for value in self.inputs.values() if value.suspension_id == suspension_id),
                None,
            )
            self.inbox.add(event_id)
            if request is None:
                return None
            self._commit_input(request, commitment)
            return self._event(item, "input.request_created", input_json(request))
        else:
            raise ConversationProblem(422, "event_unsupported", "Runtime event type is unsupported")
        self.inbox.add(event_id)
        return self._event(item, event_type, data)

    @staticmethod
    def _commit_input(request: InputRequest, commitment: tuple[UUID, UUID, UUID]) -> None:
        run_id, checkpoint_id, request_id = commitment
        if (request.run_id, request.checkpoint_id, request.input_request_id) != (
            run_id, checkpoint_id, request_id,
        ):
            raise ConversationProblem(409, "suspension_conflict", "Suspension identity conflicts")
        request.state = "pending"

    async def answer_input(
        self, owner_id: UUID, request_id: UUID, idempotency_key: str, run_id: UUID, response: Any
    ) -> tuple[UUID, int]:
        request = self.inputs.get(request_id)
        if request is None:
            raise ConversationProblem(404, "input_request_not_found", "Input request was not found")
        item = self._owned(owner_id, request.conversation_id)
        digest = hashlib.sha256(
            canonical_json({"run_id": run_id, "response": response})
        ).hexdigest()
        key = (owner_id, f"input:{request_id}", idempotency_key)
        if key in self.idempotency:
            old_digest, result = self.idempotency[key]
            if old_digest != digest:
                raise ConversationProblem(409, "idempotency_conflict", "Idempotency key was reused")
            return result
        if request.state != "pending":
            raise ConversationProblem(
                409, "input_already_answered", "Input request was already answered"
            )
        request.state, request.response, request.response_run_id = "answered", response, run_id
        sequence = self._event(
            item, "input.response.accepted", {"input_request_id": str(request_id)}
        )
        self.outbox.append(
            {
                "type": "porfirium.run.requested.v1",
                "user_id": str(owner_id),
                "conversation_id": str(item.conversation_id),
                "thread_id": str(item.thread_id),
                "release_id": str(item.release_id),
                "run_id": str(run_id),
                "delegation_grant_id": str(request.delegation_grant_id),
                "configuration_revision_id": (
                    str(item.configuration_revision_id) if item.configuration_revision_id else None
                ),
                "starting_checkpoint_id": str(request.checkpoint_id),
                "trigger": {"type": "user_response", "id": str(request_id)},
            }
        )
        result = (request_id, sequence)
        self.idempotency[key] = (digest, result)
        return result
