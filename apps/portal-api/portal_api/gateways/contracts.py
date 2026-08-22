from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol


class GatewayError(RuntimeError):
    """Normalized failure raised by a gateway adapter."""


class GatewayConfigurationError(GatewayError):
    """The selected gateway provider or its configuration is invalid."""


class GatewayProtocolError(GatewayError):
    """The gateway returned a response that violates the platform contract."""


class GatewayUpstreamError(GatewayError):
    """The selected gateway or its upstream service rejected or failed the request."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Mapping[str, object]


@dataclass(frozen=True)
class ModelRequest:
    model: str
    input: object
    correlation_id: str
    instructions: str | None = None
    max_output_tokens: int | None = None
    tools: tuple[str, ...] = ()
    tool_definitions: tuple[ToolDefinition, ...] = ()
    tool_choice: object | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    text: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ModelResponse:
    payload: Mapping[str, object]


@dataclass(frozen=True)
class ModelStreamEvent:
    type: str
    payload: Mapping[str, object]

    @property
    def delta(self) -> str:
        return str(self.payload.get("delta", ""))


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]
    correlation_id: str
    max_result_bytes: int


@dataclass(frozen=True)
class ToolResult:
    payload: Mapping[str, object]


class ModelGateway(Protocol):
    async def respond(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...


class ToolGateway(Protocol):
    async def list_tools(self) -> list[ToolDefinition]: ...

    async def call_tool(self, call: ToolCall) -> ToolResult: ...
