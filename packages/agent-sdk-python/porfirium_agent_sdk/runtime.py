from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import grpc

from porfirium_agent_sdk.errors import PlatformError
from porfirium_agent_sdk.proto import runtime_pb2 as pb


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
    ) -> None:
        self.endpoint = endpoint
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.lease_epoch = lease_epoch
        self.run_capability = run_capability
        self.sdk_version = sdk_version
        self._last_ack = 0
        self._pending: dict[int, pb.AgentFrame] = {}
        self._channel: grpc.aio.Channel | None = None
        self._call = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(buffer_frames)
        self.cancelled = asyncio.Event()
        self.deadline_epoch_seconds: float | None = None

    def _identity(self, sequence: int, idempotency_key: str | None = None) -> pb.FrameIdentity:
        return pb.FrameIdentity(
            protocol_version="1.0",
            run_id=str(self.run_id),
            attempt_id=str(self.attempt_id),
            lease_epoch=self.lease_epoch,
            sequence=sequence,
            idempotency_key=idempotency_key or str(uuid4()),
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

    def message(
        self, message_id: UUID | None = None, content_type: str = "text/plain"
    ) -> MessageStream:
        return MessageStream(self, message_id or uuid4(), content_type)


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
