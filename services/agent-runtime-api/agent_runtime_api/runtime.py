from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.timestamp_pb2 import Timestamp

from agent_runtime_api.auth import CapabilityError, RunCapability, decode_capability
from agent_runtime_api.proto import runtime_pb2 as pb

MAX_FRAME_BYTES = 16 * 1024
MAX_IN_FLIGHT_FRAMES = 32
MAX_MESSAGE_BYTES = 256 * 1024

EVENTS = {
    "message_started": (
        "porfirium.conversation.event.message_started",
        "porfirium.message.started.v1",
    ),
    "message_delta": ("porfirium.message.delta.accepted", "porfirium.message.delta.v1"),
    "message_completed": (
        "porfirium.conversation.event.message_completed",
        "porfirium.message.completed.v1",
    ),
    "message_interrupted": (
        "porfirium.conversation.event.message_interrupted",
        "porfirium.message.interrupted.v1",
    ),
    "input_request_proposed": (
        "porfirium.conversation.event.input_request_proposed",
        "porfirium.input.request_proposed.v1",
    ),
    "suspension_committed": (
        "porfirium.run.event.suspension_committed",
        "porfirium.run.suspension_committed.v1",
    ),
    "result_proposed": ("porfirium.run.event.result_proposed", "porfirium.run.result_proposed.v1"),
}


def _error(
    identity: pb.FrameIdentity, code: str, message: str, retryable: bool = False
) -> pb.PlatformFrame:
    return pb.PlatformFrame(
        run_id=identity.run_id,
        attempt_id=identity.attempt_id,
        lease_epoch=identity.lease_epoch,
        sequence=identity.sequence,
        error=pb.ProtocolError(
            code=code, safe_message=message, retryable=retryable, correlation_id=str(uuid4())
        ),
    )


def _validate_identity(identity: pb.FrameIdentity, capability: RunCapability) -> None:
    if identity.protocol_version != "1.0":
        raise ValueError("unsupported_protocol")
    if (
        UUID(identity.run_id) != capability.run_id
        or UUID(identity.attempt_id) != capability.attempt_id
        or identity.lease_epoch != capability.lease_epoch
        or identity.sequence < 0
        or not identity.idempotency_key
        or len(identity.idempotency_key) > 128
    ):
        raise ValueError("identity_mismatch")


def _event(capability: RunCapability, frame: pb.AgentFrame, event_id: UUID) -> tuple[str, dict]:
    kind = frame.WhichOneof("payload")
    subject, event_type = EVENTS[kind]
    data = MessageToDict(getattr(frame, kind), preserving_proto_field_name=True)
    if kind == "message_delta":
        content = bytes(getattr(frame, kind).content_utf8).decode("utf-8")
        data["content"] = content
        data.pop("content_utf8", None)
    elif kind == "message_completed":
        content = bytes(getattr(frame, kind).canonical_content_utf8).decode("utf-8")
        if len(content.encode()) > MAX_MESSAGE_BYTES:
            raise ValueError("message_too_large")
        data["content"] = content
        data.pop("canonical_content_utf8", None)
    envelope = {
        "specversion": "1.0",
        "type": event_type,
        "id": str(event_id),
        "source": "agent-runtime-api",
        "subject": f"run/{capability.run_id}",
        "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "user_id": str(capability.user_id),
        "conversation_id": str(capability.conversation_id),
        "thread_id": str(capability.thread_id),
        "run_id": str(capability.run_id),
        "attempt_id": str(capability.attempt_id),
        "lease_epoch": capability.lease_epoch,
        "correlation_id": str(event_id),
        "causation_id": frame.identity.idempotency_key,
        "schema_version": 1,
        "aggregate_sequence": frame.identity.sequence,
        "data": data,
    }
    return subject, envelope


class RuntimeService:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def connect(self, request_iterator, context):
        capability: RunCapability | None = None
        async for frame in request_iterator:
            identity = frame.identity
            if frame.ByteSize() > MAX_FRAME_BYTES:
                yield _error(identity, "frame_too_large", "Frame exceeds the runtime limit")
                continue
            kind = frame.WhichOneof("payload")
            if capability is None:
                if kind != "hello":
                    yield _error(identity, "hello_required", "First frame must be hello")
                    return
                try:
                    capability = decode_capability(
                        frame.hello.run_capability, os.environ["RUN_CAPABILITY_SECRET"]
                    )
                    _validate_identity(identity, capability)
                    resume = await self._activate(capability)
                except (CapabilityError, KeyError, ValueError):
                    yield _error(identity, "capability_invalid", "Run capability is invalid")
                    return
                deadline = Timestamp(seconds=capability.deadline)
                yield pb.PlatformFrame(
                    run_id=identity.run_id,
                    attempt_id=identity.attempt_id,
                    lease_epoch=identity.lease_epoch,
                    sequence=identity.sequence,
                    hello_accepted=pb.HelloAccepted(
                        resume_after_sequence=resume,
                        deadline=deadline,
                        max_frame_bytes=MAX_FRAME_BYTES,
                        max_in_flight_frames=MAX_IN_FLIGHT_FRAMES,
                    ),
                )
                continue
            try:
                _validate_identity(identity, capability)
                if identity.sequence < 1:
                    raise ValueError("sequence_out_of_order")
                event_id = await self._accept(capability, frame)
            except ValueError as exc:
                code = str(exc)
                yield _error(identity, code, code.replace("_", " ").capitalize())
                if code in {"stale_epoch", "identity_mismatch"}:
                    return
                continue
            yield pb.PlatformFrame(
                run_id=identity.run_id,
                attempt_id=identity.attempt_id,
                lease_epoch=identity.lease_epoch,
                sequence=identity.sequence,
                acknowledgement=pb.Acknowledgement(
                    accepted_sequence=identity.sequence,
                    durable_event_id=str(event_id) if event_id else "",
                ),
            )

    async def _activate(self, cap: RunCapability) -> int:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                "SELECT attempt_id, lease_epoch, last_sequence FROM runtime_attempts "
                "WHERE run_id=$1 FOR UPDATE",
                cap.run_id,
            )
            if row and row["lease_epoch"] > cap.lease_epoch:
                raise ValueError("stale_epoch")
            if (
                row
                and row["lease_epoch"] == cap.lease_epoch
                and row["attempt_id"] != cap.attempt_id
            ):
                raise ValueError("attempt_mismatch")
            if not row or row["lease_epoch"] < cap.lease_epoch:
                await connection.execute(
                    "INSERT INTO runtime_attempts(run_id,attempt_id,lease_epoch,user_id,"
                    "conversation_id,thread_id,deadline) "
                    "VALUES($1,$2,$3,$4,$5,$6,to_timestamp($7)) "
                    "ON CONFLICT(run_id) DO UPDATE SET attempt_id=excluded.attempt_id,"
                    "lease_epoch=excluded.lease_epoch,user_id=excluded.user_id,"
                    "conversation_id=excluded.conversation_id,thread_id=excluded.thread_id,"
                    "deadline=excluded.deadline,last_sequence=0,updated_at=now()",
                    cap.run_id,
                    cap.attempt_id,
                    cap.lease_epoch,
                    cap.user_id,
                    cap.conversation_id,
                    cap.thread_id,
                    cap.deadline,
                )
                return 0
            return int(row["last_sequence"])

    async def _accept(self, cap: RunCapability, frame: pb.AgentFrame) -> UUID | None:
        identity = frame.identity
        kind = frame.WhichOneof("payload")
        if kind in {None, "hello"}:
            raise ValueError("invalid_frame")
        event_id = uuid4() if kind in EVENTS else None
        async with self.pool.acquire() as connection, connection.transaction():
            attempt = await connection.fetchrow(
                "SELECT attempt_id,lease_epoch,last_sequence FROM runtime_attempts "
                "WHERE run_id=$1 FOR UPDATE",
                cap.run_id,
            )
            if not attempt or attempt["lease_epoch"] != cap.lease_epoch:
                raise ValueError("stale_epoch")
            existing = await connection.fetchrow(
                "SELECT sequence,durable_event_id FROM accepted_frames WHERE run_id=$1 AND "
                "attempt_id=$2 AND lease_epoch=$3 AND idempotency_key=$4",
                cap.run_id,
                cap.attempt_id,
                cap.lease_epoch,
                identity.idempotency_key,
            )
            if existing:
                if existing["sequence"] != identity.sequence:
                    raise ValueError("idempotency_conflict")
                return existing["durable_event_id"]
            if identity.sequence != attempt["last_sequence"] + 1:
                raise ValueError("sequence_out_of_order")
            if kind == "message_delta":
                try:
                    content = bytes(frame.message_delta.content_utf8).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("invalid_utf8") from exc
                if not content or len(content.encode()) > 4096:
                    raise ValueError("chunk_size_invalid")
            if kind == "message_completed":
                completed = frame.message_completed
                content = bytes(completed.canonical_content_utf8)
                if (
                    len(content) != completed.content_bytes
                    or hashlib.sha256(content).hexdigest() != completed.content_sha256
                    or completed.chunk_count > 65536
                ):
                    raise ValueError("completion_hash_invalid")
            if kind in EVENTS:
                subject, envelope = _event(cap, frame, event_id)
                await connection.execute(
                    "INSERT INTO outbox_events(event_id,subject,payload) VALUES($1,$2,$3::jsonb)",
                    event_id,
                    subject,
                    json.dumps(envelope, separators=(",", ":")),
                )
            await connection.execute(
                "INSERT INTO accepted_frames(run_id,attempt_id,lease_epoch,sequence,"
                "idempotency_key,payload_type,durable_event_id) VALUES($1,$2,$3,$4,$5,$6,$7)",
                cap.run_id,
                cap.attempt_id,
                cap.lease_epoch,
                identity.sequence,
                identity.idempotency_key,
                kind,
                event_id,
            )
            await connection.execute(
                "UPDATE runtime_attempts SET last_sequence=$2,updated_at=now(),"
                "last_heartbeat_at=CASE WHEN $3='heartbeat' THEN now() ELSE last_heartbeat_at END "
                "WHERE run_id=$1",
                cap.run_id,
                identity.sequence,
                kind,
            )
        return event_id


def add_runtime_service(server: grpc.aio.Server, service: RuntimeService) -> None:
    handler = grpc.stream_stream_rpc_method_handler(
        service.connect,
        request_deserializer=pb.AgentFrame.FromString,
        response_serializer=pb.PlatformFrame.SerializeToString,
    )
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "porfirium.runtime.v1.AgentRuntime", {"Connect": handler}
            ),
        )
    )
