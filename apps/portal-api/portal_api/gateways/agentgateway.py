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

PLATFORM_TO_GATEWAY_TOOL = {
    "demo_time-get_current_time": "time_get_current_time",
    "demo_time-convert_time": "time_convert_time",
    "demo_mtg_catalog-search_cards": "mtg-catalog_search_cards",
    "demo_mtg_catalog-get_card": "mtg-catalog_get_card",
    "demo_mtg_catalog-compare_cards": "mtg-catalog_compare_cards",
    "demo_mtg_catalog-list_sets": "mtg-catalog_list_sets",
}
GATEWAY_TO_PLATFORM_TOOL = {
    gateway_name: platform_name
    for platform_name, gateway_name in PLATFORM_TO_GATEWAY_TOOL.items()
}


def _trace_headers(correlation_id: str) -> dict[str, str]:
    return {
        "traceparent": f"00-{correlation_id}-{uuid.uuid4().hex[:16]}-01",
        "x-request-id": correlation_id,
    }


class AgentgatewayModelGateway:
    """OpenAI Responses adapter for Agentgateway's model endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        model_alias: str = "default",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=10)
        self._model_alias = model_alias
        self._transport = transport

    def _body(self, request: ModelRequest, *, stream: bool) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._model_alias,
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
        if request.tool_definitions:
            body["tools"] = [
                {
                    "type": "function",
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": dict(definition.input_schema),
                    "strict": True,
                }
                for definition in request.tool_definitions
            ]
        elif request.tools and request.tool_choice != "none":
            raise GatewayProtocolError("model_tool_definitions_missing")
        if request.text is not None:
            body["text"] = dict(request.text)
        return body

    async def respond(self, request: ModelRequest) -> ModelResponse:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/v1/responses",
                    json=self._body(request, stream=False),
                    headers=_trace_headers(request.correlation_id),
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
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/v1/responses",
                    json=self._body(request, stream=True),
                    headers={
                        "Accept": "text/event-stream",
                        **_trace_headers(request.correlation_id),
                    },
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
                            raise GatewayProtocolError(
                                "model_stream_event_invalid_json"
                            ) from exc
                        if not isinstance(payload, dict) or not isinstance(
                            payload.get("type"), str
                        ):
                            raise GatewayProtocolError("model_stream_event_invalid")
                        yield ModelStreamEvent(type=payload["type"], payload=payload)
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError("model_gateway_stream_failed") from exc


class AgentgatewayToolGateway:
    """MCP adapter that preserves the platform's stable tool identifiers."""

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

    async def _rpc(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        correlation_id: str,
    ) -> Mapping[str, object]:
        request_id = uuid.uuid4().hex
        headers = {
            "Accept": "application/json, text/event-stream",
            **_trace_headers(correlation_id),
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                initialize_id = uuid.uuid4().hex
                initialize_response = await client.post(
                    f"{self._base_url}/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": initialize_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "porfirium", "version": "1.0"},
                        },
                    },
                    headers=headers,
                )
                initialize_response.raise_for_status()
                initialized = self._decode_payload(
                    initialize_response.content,
                    initialize_response.headers.get("content-type", ""),
                )
                if isinstance(initialized.get("error"), Mapping):
                    raise GatewayUpstreamError("tool_gateway_initialize_rejected")
                if initialized.get("id") != initialize_id or not isinstance(
                    initialized.get("result"), Mapping
                ):
                    raise GatewayProtocolError("tool_gateway_initialize_invalid")
                session_id = initialize_response.headers.get("mcp-session-id")
                if session_id:
                    headers["mcp-session-id"] = session_id
                notification = await client.post(
                    f"{self._base_url}/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    },
                    headers=headers,
                )
                notification.raise_for_status()
                response = await client.post(
                    f"{self._base_url}/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": dict(params),
                    },
                    headers=headers,
                )
                response.raise_for_status()
                raw = response.content
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError(f"tool_gateway_{method.replace('/', '_')}_failed") from exc

        payload = self._decode_payload(raw, response.headers.get("content-type", ""))
        error = payload.get("error")
        if error is not None:
            if payload.get("id") not in {request_id, None}:
                raise GatewayProtocolError("tool_gateway_response_id_mismatch")
            if not isinstance(error, Mapping):
                raise GatewayProtocolError("tool_gateway_error_invalid")
            raise GatewayUpstreamError(f"tool_gateway_{method.replace('/', '_')}_rejected")
        if payload.get("id") != request_id:
            raise GatewayProtocolError("tool_gateway_response_id_mismatch")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise GatewayProtocolError("tool_gateway_result_not_object")
        return result

    @staticmethod
    def _decode_payload(raw: bytes, content_type: str) -> Mapping[str, object]:
        try:
            if content_type.split(";", 1)[0].strip() == "text/event-stream":
                events = []
                for line in raw.decode().splitlines():
                    if line.startswith("data:"):
                        value = line.removeprefix("data:").strip()
                        if value and value != "[DONE]":
                            events.append(json.loads(value))
                payload = events[-1] if events else None
            else:
                payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayProtocolError("tool_gateway_invalid_json") from exc
        if not isinstance(payload, Mapping):
            raise GatewayProtocolError("tool_gateway_response_not_object")
        if payload.get("jsonrpc") != "2.0":
            raise GatewayProtocolError("tool_gateway_invalid_jsonrpc")
        return payload

    async def list_tools(self) -> list[ToolDefinition]:
        result = await self._rpc("tools/list", {}, correlation_id=uuid.uuid4().hex)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise GatewayProtocolError("tool_discovery_tools_not_array")
        definitions: list[ToolDefinition] = []
        for tool in tools:
            if not isinstance(tool, Mapping) or not isinstance(tool.get("name"), str):
                raise GatewayProtocolError("tool_discovery_tool_invalid")
            platform_name = GATEWAY_TO_PLATFORM_TOOL.get(tool["name"])
            if platform_name is None:
                continue
            schema = tool.get("inputSchema", {})
            if not isinstance(schema, Mapping):
                raise GatewayProtocolError("tool_discovery_schema_invalid")
            definitions.append(
                ToolDefinition(
                    name=platform_name,
                    description=str(tool.get("description", "")),
                    input_schema=schema,
                )
            )
        return definitions

    async def call_tool(self, call: ToolCall) -> ToolResult:
        gateway_name = PLATFORM_TO_GATEWAY_TOOL.get(call.name)
        if gateway_name is None:
            raise GatewayUpstreamError("tool_gateway_tool_unmapped")
        result = await self._rpc(
            "tools/call",
            {"name": gateway_name, "arguments": dict(call.arguments)},
            correlation_id=call.correlation_id,
        )
        raw_result = json.dumps(result, separators=(",", ":")).encode()
        if len(raw_result) > call.max_result_bytes:
            raise GatewayProtocolError("tool_result_too_large")
        return ToolResult(payload=result)
