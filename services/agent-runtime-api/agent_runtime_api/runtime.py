from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg
import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp

from agent_runtime_api.auth import CapabilityError, RunCapability, decode_capability
from agent_runtime_api.model_gateway import ModelGateway, ModelGatewayError
from agent_runtime_api.proto import runtime_pb2 as pb

MAX_FRAME_BYTES = 16 * 1024
MAX_IN_FLIGHT_FRAMES = 32
MAX_MESSAGE_BYTES = 256 * 1024
SUPPORTED_PROTOCOL_MAJOR = 1
SUPPORTED_PROTOCOL_MINORS = frozenset({0, 1})

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


@dataclass(frozen=True, slots=True)
class ToolExecution:
    result: object
    is_error: bool = False


class DelegatedToolGateway(Protocol):
    """Gateway boundary that must enforce the delegated user token for this attempt."""

    async def invoke(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        invocation_id: UUID,
        capability: RunCapability,
    ) -> ToolExecution: ...


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
    try:
        major, minor = (int(value) for value in identity.protocol_version.split(".", 1))
    except (TypeError, ValueError):
        raise ValueError("unsupported_protocol") from None
    if major != SUPPORTED_PROTOCOL_MAJOR or minor not in SUPPORTED_PROTOCOL_MINORS:
        raise ValueError("unsupported_protocol")
    trace_match = re.fullmatch(
        r"00-((?!0{32})[0-9a-f]{32})-((?!0{16})[0-9a-f]{16})-[0-9a-f]{2}",
        identity.traceparent,
    )
    if (
        UUID(identity.run_id) != capability.run_id
        or UUID(identity.attempt_id) != capability.attempt_id
        or identity.lease_epoch != capability.lease_epoch
        or identity.sequence < 0
        or not identity.idempotency_key
        or len(identity.idempotency_key) > 128
        or trace_match is None
        or trace_match.group(1) != capability.trace_id
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
        "correlation_id": str(UUID(hex=capability.trace_id)),
        "causation_id": _causation_id(frame.identity.idempotency_key),
        "traceparent": frame.identity.traceparent,
        "schema_version": 1,
        "aggregate_sequence": frame.identity.sequence,
        "data": data,
    }
    return subject, envelope


def _causation_id(idempotency_key: str) -> str:
    try:
        return str(UUID(idempotency_key))
    except ValueError:
        return str(UUID(bytes=hashlib.sha256(idempotency_key.encode()).digest()[:16]))


class RuntimeService:
    def __init__(
        self,
        pool: asyncpg.Pool,
        model_gateway: ModelGateway | None = None,
        tool_gateway: DelegatedToolGateway | None = None,
    ) -> None:
        self.pool = pool
        self.model_gateway = model_gateway
        self.tool_gateway = tool_gateway

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
                run_input = pb.RunInput()
                if capability.run_input:
                    run_input.trigger_type = str(capability.run_input["trigger_type"])
                    run_input.trigger_id = str(capability.run_input["trigger_id"])
                    ParseDict(capability.run_input.get("value"), run_input.value)
                    if capability.starting_checkpoint_id:
                        run_input.starting_checkpoint_id = str(
                            capability.starting_checkpoint_id
                        )
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
                        run_input=run_input,
                    ),
                )
                continue
            try:
                _validate_identity(identity, capability)
                if identity.sequence < 1:
                    raise ValueError("sequence_out_of_order")
                model_result = None
                tool_result = None
                if kind == "model_call":
                    model_result = await self._call_model(capability, frame.model_call)
                if kind == "tool_call":
                    tool_result = await self._call_tool(capability, frame.tool_call)
                event_id = await self._accept(capability, frame)
            except (ModelGatewayError, ValueError) as exc:
                code = str(exc)
                yield _error(identity, code, code.replace("_", " ").capitalize())
                if code in {"stale_epoch", "identity_mismatch"}:
                    return
                continue
            if model_result is not None:
                usage = Struct()
                usage.update(model_result.usage)
                yield pb.PlatformFrame(
                    run_id=identity.run_id,
                    attempt_id=identity.attempt_id,
                    lease_epoch=identity.lease_epoch,
                    sequence=identity.sequence,
                    model_result=pb.ModelResult(
                        request_id=frame.model_call.request_id,
                        content_utf8=model_result.content.encode(),
                        finish_reason=model_result.finish_reason,
                        usage=usage,
                    ),
                )
            if tool_result is not None:
                result_frame = pb.ToolResult(
                    invocation_id=frame.tool_call.invocation_id,
                    is_error=tool_result.is_error,
                )
                try:
                    ParseDict(tool_result.result, result_frame.result)
                except (TypeError, ValueError):
                    yield _error(identity, "tool_response_invalid", "Tool response is invalid")
                    continue
                yield pb.PlatformFrame(
                    run_id=identity.run_id,
                    attempt_id=identity.attempt_id,
                    lease_epoch=identity.lease_epoch,
                    sequence=identity.sequence,
                    tool_result=result_frame,
                )
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

    async def _call_model(self, cap: RunCapability, call: pb.ModelCall):
        if self.model_gateway is None:
            raise ValueError("model_gateway_unavailable")
        if call.model not in cap.models:
            raise ValueError("model_forbidden")
        if (
            not call.request_id
            or len(call.request_id) > 128
            or not call.prompt
            or len(call.prompt.encode()) > 12 * 1024
            or not 1 <= call.max_output_tokens <= 4096
        ):
            raise ValueError("model_request_invalid")
        return await self.model_gateway.respond(
            model=call.model,
            prompt=call.prompt,
            max_output_tokens=call.max_output_tokens,
            metadata={"run_id": str(cap.run_id), "user_id": str(cap.user_id)},
        )

    async def _call_tool(self, cap: RunCapability, call: pb.ToolCall) -> ToolExecution:
        if call.tool not in cap.tools:
            raise ValueError("tool_forbidden")
        try:
            invocation_id = UUID(call.invocation_id)
        except ValueError as error:
            raise ValueError("tool_request_invalid") from error
        arguments = MessageToDict(call.arguments, preserving_proto_field_name=True)
        if (
            not call.tool
            or len(call.tool) > 128
            or not isinstance(arguments, dict)
            or len(json.dumps(arguments, ensure_ascii=False).encode()) > 8 * 1024
        ):
            raise ValueError("tool_request_invalid")
        if self.tool_gateway is None:
            raise ValueError("tool_delegation_unavailable")
        request_digest = hashlib.sha256(
            json.dumps(
                {"tool": call.tool, "arguments": arguments},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                f"tool:{cap.run_id}:{invocation_id}",
            )
            existing = await connection.fetchrow(
                "SELECT request_sha256,state,result,is_error FROM tool_invocations "
                "WHERE run_id=$1 AND invocation_id=$2 FOR UPDATE",
                cap.run_id,
                invocation_id,
            )
            if existing:
                if existing["request_sha256"] != request_digest:
                    raise ValueError("tool_idempotency_conflict")
                if existing["state"] != "completed":
                    raise ValueError("tool_outcome_ambiguous")
                stored = existing["result"]
                return ToolExecution(
                    json.loads(stored) if isinstance(stored, str) else stored,
                    bool(existing["is_error"]),
                )
            await connection.execute(
                "INSERT INTO tool_invocations(run_id,invocation_id,attempt_id,lease_epoch,"
                "request_sha256,state) VALUES($1,$2,$3,$4,$5,'executing')",
                cap.run_id,
                invocation_id,
                cap.attempt_id,
                cap.lease_epoch,
                request_digest,
            )
        result = await self.tool_gateway.invoke(
            tool=call.tool,
            arguments=arguments,
            invocation_id=invocation_id,
            capability=cap,
        )
        if len(json.dumps(result.result, ensure_ascii=False).encode()) > 12 * 1024:
            raise ValueError("tool_response_invalid")
        async with self.pool.acquire() as connection, connection.transaction():
            updated = await connection.execute(
                "UPDATE tool_invocations SET state='completed',result=$3::jsonb,is_error=$4,"
                "completed_at=now() WHERE run_id=$1 AND invocation_id=$2 "
                "AND state='executing'",
                cap.run_id,
                invocation_id,
                json.dumps(result.result, separators=(",", ":"), ensure_ascii=False),
                result.is_error,
            )
            if updated != "UPDATE 1":
                raise ValueError("tool_outcome_ambiguous")
        return result

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
