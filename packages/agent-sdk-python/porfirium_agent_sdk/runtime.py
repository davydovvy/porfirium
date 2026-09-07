from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from porfirium_agent_sdk.errors import PlatformError
from porfirium_agent_sdk.proto import runtime_pb2 as pb


@dataclass(frozen=True, slots=True)
class RunInput:
    trigger_type: str
    trigger_id: UUID
    value: object
    starting_checkpoint_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str
    finish_reason: str
    usage: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolResponse:
    result: object
    is_error: bool


def decode_run_input(value: pb.RunInput) -> RunInput | None:
    if not value.trigger_type:
        return None
    serialized = {
        "trigger_type": value.trigger_type,
        "trigger_id": value.trigger_id,
        "value": MessageToDict(value.value),
        "starting_checkpoint_id": value.starting_checkpoint_id or None,
    }
    if len(json.dumps(serialized).encode()) > 24576:
        raise PlatformError("run_input_too_large", "Run input exceeds the SDK limit")
    try:
        return RunInput(
            value.trigger_type,
            UUID(value.trigger_id),
            serialized["value"],
            UUID(value.starting_checkpoint_id) if value.starting_checkpoint_id else None,
        )
    except ValueError as error:
        raise PlatformError("run_input_invalid", "Run input identity is invalid") from error


class RuntimeClient:
    """Reconnectable, ordered Agent Runtime API stream.

    Only acknowledged frames leave the in-memory retransmission buffer. The agent receives the
    run capability, never infrastructure credentials.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        run_id: UUID,
        attempt_id: UUID,
        lease_epoch: int,
        run_capability: str,
        sdk_version: str = "0.2.0",
        buffer_frames: int = 32,
        trace_id: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.lease_epoch = lease_epoch
        self.run_capability = run_capability
        self.trace_id = trace_id or run_id.hex
        self.sdk_version = sdk_version
        self._last_ack = 0
        self._pending: dict[int, pb.AgentFrame] = {}
        self._channel: grpc.aio.Channel | None = None
        self._call = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(buffer_frames)
        self.cancelled = asyncio.Event()
        self.deadline_epoch_seconds: float | None = None
        self.run_input: RunInput | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environment is None else environment
        endpoint = values.get("PORFIRIUM_RUNTIME_URL", "")
        capability = values.get("PORFIRIUM_RUN_CAPABILITY", "")
        if not endpoint or len(endpoint) > 512 or not capability or len(capability) > 32768:
            raise PlatformError("bootstrap_invalid", "Runtime bootstrap configuration is invalid")
        try:
            encoded, signature = capability.split(".")
            if not encoded or not signature:
                raise ValueError
            payload = json.loads(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            )
            if not isinstance(payload, dict):
                raise ValueError
            run_id = UUID(payload["run_id"])
            attempt_id = UUID(payload["attempt_id"])
            lease_epoch = int(payload["lease_epoch"])
            if lease_epoch < 1:
                raise ValueError
            trace_id = str(payload["trace_id"])
            if len(trace_id) != 32 or any(value not in "0123456789abcdef" for value in trace_id):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, binascii.Error) as error:
            raise PlatformError(
                "bootstrap_invalid", "Runtime bootstrap capability is invalid"
            ) from error
        return cls(
            endpoint,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_epoch=lease_epoch,
            run_capability=capability,
            trace_id=trace_id,
        )

    def _identity(self, sequence: int, idempotency_key: str | None = None) -> pb.FrameIdentity:
        span_id = uuid4().hex[:16]
        return pb.FrameIdentity(
            protocol_version="1.0",
            run_id=str(self.run_id),
            attempt_id=str(self.attempt_id),
            lease_epoch=self.lease_epoch,
            sequence=sequence,
            idempotency_key=idempotency_key or str(uuid4()),
            traceparent=f"00-{self.trace_id}-{span_id}-01",
        )

    async def connect(self) -> None:
        if self._channel is not None:
            await self._channel.close()
        self._channel = grpc.aio.insecure_channel(
            self.endpoint,
            options=[
                ("grpc.max_send_message_length", 16 * 1024),
                ("grpc.max_receive_message_length", 16 * 1024),
            ],
        )
        method = self._channel.stream_stream(
            "/porfirium.runtime.v1.AgentRuntime/Connect",
            request_serializer=pb.AgentFrame.SerializeToString,
            response_deserializer=pb.PlatformFrame.FromString,
        )
        self._call = method()
        await self._call.write(
            pb.AgentFrame(
                identity=self._identity(0, "hello"),
                hello=pb.Hello(
                    run_capability=self.run_capability,
                    last_acknowledged_sequence=self._last_ack,
                    sdk_version=self.sdk_version,
                ),
            )
        )
        response = await self._call.read()
        if not response or response.WhichOneof("payload") != "hello_accepted":
            await self._raise_response(response)
        self._last_ack = response.hello_accepted.resume_after_sequence
        self.deadline_epoch_seconds = response.hello_accepted.deadline.seconds
        received_input = response.hello_accepted.run_input
        self.run_input = decode_run_input(received_input)
        for sequence in sorted(self._pending):
            if sequence > self._last_ack:
                await self._call.write(self._pending[sequence])

    async def close(self) -> None:
        if self._call is not None:
            await self._call.done_writing()
        if self._channel is not None:
            await self._channel.close()
        self._call = self._channel = None

    async def _raise_response(self, response) -> None:
        if response and response.WhichOneof("payload") == "error":
            error = response.error
            raise PlatformError(
                error.code,
                error.safe_message,
                retryable=error.retryable,
                correlation_id=error.correlation_id,
            )
        raise PlatformError("transport_unavailable", "Runtime stream closed", retryable=True)

    async def send(self, **payload) -> pb.Acknowledgement:
        async with self._slots, self._lock:
            if self._call is None:
                await self.connect()
            sequence = max([self._last_ack, *self._pending], default=0) + 1
            frame = pb.AgentFrame(identity=self._identity(sequence), **payload)
            self._pending[sequence] = frame
            for attempt in range(4):
                try:
                    if self._call is None:
                        await self.connect()
                    else:
                        await self._call.write(frame)
                    while True:
                        response = await self._call.read()
                        kind = response.WhichOneof("payload") if response else None
                        if kind == "cancellation":
                            self.cancelled.set()
                            continue
                        if kind == "error":
                            await self._raise_response(response)
                        if kind == "acknowledgement":
                            accepted = response.acknowledgement.accepted_sequence
                            self._last_ack = max(self._last_ack, accepted)
                            for sent in [value for value in self._pending if value <= accepted]:
                                self._pending.pop(sent)
                            return response.acknowledgement
                except grpc.aio.AioRpcError as exc:
                    self._call = None
                    if exc.code() not in {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.CANCELLED}:
                        raise PlatformError("transport_error", "Runtime transport failed") from exc
                    if attempt == 3:
                        raise PlatformError(
                            "transport_unavailable", "Runtime is unavailable", retryable=True
                        ) from exc
                    await asyncio.sleep(0.1 * (2**attempt))
            raise AssertionError("unreachable")

    async def model(
        self,
        prompt: str,
        *,
        model: str = "default",
        max_output_tokens: int = 2048,
        request_id: UUID | None = None,
    ) -> ModelResponse:
        if (
            not prompt
            or len(prompt.encode()) > 12 * 1024
            or not model
            or len(model) > 128
            or not 1 <= max_output_tokens <= 4096
        ):
            raise ValueError("model request exceeds SDK bounds")
        stable_request_id = request_id or uuid4()
        async with self._slots, self._lock:
            if self._call is None:
                await self.connect()
            sequence = max([self._last_ack, *self._pending], default=0) + 1
            frame = pb.AgentFrame(
                identity=self._identity(sequence, str(stable_request_id)),
                model_call=pb.ModelCall(
                    request_id=str(stable_request_id),
                    model=model,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                ),
            )
            self._pending[sequence] = frame
            await self._call.write(frame)
            result: ModelResponse | None = None
            while True:
                response = await self._call.read()
                kind = response.WhichOneof("payload") if response else None
                if kind == "cancellation":
                    self.cancelled.set()
                    continue
                if kind == "error":
                    await self._raise_response(response)
                if kind == "model_result":
                    received = response.model_result
                    if received.request_id != str(stable_request_id):
                        raise PlatformError("model_response_mismatch", "Model response mismatched")
                    try:
                        content = bytes(received.content_utf8).decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise PlatformError(
                            "model_response_invalid", "Model response was not UTF-8"
                        ) from error
                    if not content or len(content.encode()) > 12 * 1024:
                        raise PlatformError(
                            "model_response_invalid", "Model response exceeded bounds"
                        )
                    result = ModelResponse(
                        content,
                        received.finish_reason,
                        MessageToDict(received.usage),
                    )
                    continue
                if kind == "acknowledgement":
                    accepted = response.acknowledgement.accepted_sequence
                    self._last_ack = max(self._last_ack, accepted)
                    for sent in [value for value in self._pending if value <= accepted]:
                        self._pending.pop(sent)
                    if result is None:
                        raise PlatformError(
                            "model_response_missing", "Model gateway returned no response"
                        )
                    return result

    def message(
        self, message_id: UUID | None = None, content_type: str = "text/plain"
    ) -> MessageStream:
        return MessageStream(self, message_id or uuid4(), content_type)

    async def tool(
        self,
        tool: str,
        arguments: Mapping[str, object],
        *,
        invocation_id: UUID | None = None,
    ) -> ToolResponse:
        if not tool or len(tool) > 128:
            raise ValueError("tool name exceeds SDK bounds")
        encoded_arguments = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        if len(encoded_arguments.encode()) > 8 * 1024:
            raise ValueError("tool arguments exceed SDK bounds")
        protobuf_arguments = Struct()
        try:
            protobuf_arguments.update(dict(arguments))
        except (TypeError, ValueError) as error:
            raise ValueError("tool arguments are not JSON-compatible") from error
        stable_invocation_id = invocation_id or uuid4()
        async with self._slots, self._lock:
            if self._call is None:
                await self.connect()
            sequence = max([self._last_ack, *self._pending], default=0) + 1
            frame = pb.AgentFrame(
                identity=self._identity(sequence, str(stable_invocation_id)),
                tool_call=pb.ToolCall(
                    invocation_id=str(stable_invocation_id),
                    tool=tool,
                    arguments=protobuf_arguments,
                ),
            )
            self._pending[sequence] = frame
            await self._call.write(frame)
            result: ToolResponse | None = None
            while True:
                response = await self._call.read()
                kind = response.WhichOneof("payload") if response else None
                if kind == "cancellation":
                    self.cancelled.set()
                    continue
                if kind == "error":
                    await self._raise_response(response)
                if kind == "tool_result":
                    received = response.tool_result
                    if received.invocation_id != str(stable_invocation_id):
                        raise PlatformError("tool_response_mismatch", "Tool response mismatched")
                    value = MessageToDict(received.result)
                    if len(json.dumps(value, ensure_ascii=False).encode()) > 12 * 1024:
                        raise PlatformError(
                            "tool_response_invalid", "Tool response exceeded bounds"
                        )
                    result = ToolResponse(value, received.is_error)
                    continue
                if kind == "acknowledgement":
                    accepted = response.acknowledgement.accepted_sequence
                    self._last_ack = max(self._last_ack, accepted)
                    for sent in [value for value in self._pending if value <= accepted]:
                        self._pending.pop(sent)
                    if result is None:
                        raise PlatformError(
                            "tool_response_missing", "Tool gateway returned no response"
                        )
                    return result


@dataclass(slots=True)
class MessageStream:
    client: RuntimeClient
    message_id: UUID
    content_type: str
    _chunks: list[bytes] | None = None
    _terminal: bool = False

    async def __aenter__(self) -> Self:
        self._chunks = []
        await self.client.send(
            message_started=pb.MessageStarted(
                message_id=str(self.message_id), content_type=self.content_type
            )
        )
        return self

    async def delta(self, content: str) -> None:
        if self._terminal or self._chunks is None:
            raise RuntimeError("message stream is not active")
        encoded = content.encode("utf-8")
        if not encoded or len(encoded) > 4096:
            raise ValueError("message delta must contain 1 to 4096 UTF-8 bytes")
        self._chunks.append(encoded)
        await self.client.send(
            message_delta=pb.MessageDelta(
                message_id=str(self.message_id),
                chunk_sequence=len(self._chunks),
                content_utf8=encoded,
            )
        )

    async def complete(self, finish_reason: str = "stop") -> None:
        if self._terminal or self._chunks is None:
            raise RuntimeError("message stream is not active")
        content = b"".join(self._chunks)
        if len(content) > 256 * 1024:
            raise ValueError("canonical message exceeds 256 KiB")
        await self.client.send(
            message_completed=pb.MessageCompleted(
                message_id=str(self.message_id),
                canonical_content_utf8=content,
                chunk_count=len(self._chunks),
                content_bytes=len(content),
                content_sha256=hashlib.sha256(content).hexdigest(),
                finish_reason=finish_reason,
            )
        )
        self._terminal = True

    async def interrupt(self, code: str = "agent_interrupted") -> None:
        if not self._terminal:
            await self.client.send(
                message_interrupted=pb.MessageInterrupted(
                    message_id=str(self.message_id), code=code
                )
            )
            self._terminal = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._terminal:
            if exc is None:
                await self.complete()
            else:
                await self.interrupt()
