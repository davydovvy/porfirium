from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Mapping

import httpx

from .contracts import (
    GatewayProtocolError,
    GatewayUpstreamError,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


def _trace_headers(correlation_id: str) -> dict[str, str]:
    parent_span_id = uuid.uuid4().hex[:16]
    return {
        "x-request-id": correlation_id,
        "x-bf-session-id": correlation_id,
        "traceparent": f"00-{correlation_id}-{parent_span_id}-01",
    }


class BifrostModelGateway:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        model_prefix: str = "yandex/",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10)
        self._model_prefix = model_prefix
        self._transport = transport

    def _body(self, request: ModelRequest, *, stream: bool) -> dict[str, object]:
        body: dict[str, object] = {
            "model": f"{self._model_prefix}{request.model}",
            "input": request.input,
            "metadata": dict(request.metadata),
        }
        if stream:
            body["stream"] = True
        if request.instructions is not None:
            body["instructions"] = request.instructions
        if request.max_output_tokens is not None:
            body["max_output_tokens"] = request.max_output_tokens
        if request.tool_choice is not None:
            body["tool_choice"] = request.tool_choice
            if request.tool_choice == "none":
                body["tools"] = []
        if request.text is not None:
            body["text"] = dict(request.text)
        return body

    def _headers(self, request: ModelRequest) -> dict[str, str]:
        headers = _trace_headers(request.correlation_id)
        if request.tools:
            headers["x-bf-mcp-include-tools"] = ",".join(request.tools)
        return headers

    async def respond(self, request: ModelRequest) -> ModelResponse:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/v1/responses",
                    json=self._body(request, stream=False),
                    headers=self._headers(request),
                )
                response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError("model_gateway_request_failed") from exc
        except json.JSONDecodeError as exc:
            raise GatewayProtocolError("model_response_invalid_json") from exc
        if not isinstance(payload, dict):
            raise GatewayProtocolError("model_response_not_object")
        return ModelResponse(payload=payload)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        headers = {"Accept": "text/event-stream", **self._headers(request)}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/v1/responses",
                    json=self._body(request, stream=True),
                    headers=headers,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line.removeprefix("data:").strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise GatewayProtocolError("model_stream_event_invalid_json") from exc
                        if not isinstance(payload, dict) or not isinstance(
                            payload.get("type"), str
                        ):
                            raise GatewayProtocolError("model_stream_event_invalid")
                        yield ModelStreamEvent(type=payload["type"], payload=payload)
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError("model_gateway_stream_failed") from exc


class BifrostToolGateway:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=5)
        self._transport = transport

    async def list_tools(self) -> list[ToolDefinition]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.get(f"{self._base_url}/api/mcp/clients")
                response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError("tool_discovery_failed") from exc
        except json.JSONDecodeError as exc:
            raise GatewayProtocolError("tool_discovery_invalid_json") from exc
        if not isinstance(payload, dict):
            raise GatewayProtocolError("tool_discovery_response_not_object")
        definitions: list[ToolDefinition] = []
        for client_item in payload.get("clients", []):
            if not isinstance(client_item, dict) or client_item.get("state") != "connected":
                continue
            config = client_item.get("config", {})
            client_name = config.get("name") if isinstance(config, dict) else None
            if not isinstance(client_name, str):
                continue
            for tool in client_item.get("tools", []):
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                    continue
                schema = tool.get("inputSchema", tool.get("input_schema", {}))
                definitions.append(
                    ToolDefinition(
                        name=f"{client_name}-{tool['name']}",
                        description=str(tool.get("description", "")),
                        input_schema=schema if isinstance(schema, Mapping) else {},
                    )
                )
        return definitions

    async def call_tool(self, call: ToolCall) -> ToolResult:
        raw_arguments = json.dumps(call.arguments, separators=(",", ":"))
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/v1/mcp/tool/execute",
                    json={
                        "id": call.call_id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": raw_arguments},
                    },
                    headers={
                        **_trace_headers(call.correlation_id),
                        "x-bf-mcp-include-tools": call.name,
                    },
                )
                response.raise_for_status()
                raw_result = response.content
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError("tool_execution_failed") from exc
        if len(raw_result) > call.max_result_bytes:
            raise GatewayProtocolError("tool_result_too_large")
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise GatewayProtocolError("tool_result_invalid_json") from exc
        if not isinstance(payload, dict):
            raise GatewayProtocolError("tool_result_not_object")
        return ToolResult(payload=payload)
