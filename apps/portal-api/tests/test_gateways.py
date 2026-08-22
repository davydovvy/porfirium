from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from portal_api.config import settings
from portal_api.gateways.agentgateway import (
    AgentgatewayModelGateway,
    AgentgatewayToolGateway,
)
from portal_api.gateways.contracts import (
    GatewayProtocolError,
    GatewayUpstreamError,
    ModelRequest,
    ToolCall,
    ToolDefinition,
)
from portal_api.gateways.factory import create_model_gateway, create_tool_gateway

TRACE_ID = "0123456789abcdef0123456789abcdef"


@pytest.mark.asyncio
async def test_agentgateway_model_adapter_supplies_tools_and_trace_context() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "status": "completed",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "demo_time-get_current_time",
                        "arguments": '{"timezone":"UTC"}',
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
        )

    gateway = AgentgatewayModelGateway(
        "http://agentgateway:8090/",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    response = await gateway.respond(
        ModelRequest(
            model="concrete-yandex-model-id",
            input="What time is it?",
            correlation_id=TRACE_ID,
            instructions="Use the time tool.",
            max_output_tokens=128,
            tools=("demo_time-get_current_time",),
            tool_definitions=(
                ToolDefinition(
                    name="demo_time-get_current_time",
                    description="Return the current time.",
                    input_schema={
                        "type": "object",
                        "properties": {"timezone": {"type": "string"}},
                        "required": ["timezone"],
                        "additionalProperties": False,
                    },
                ),
            ),
            tool_choice="auto",
            metadata={"turn_id": "turn-1"},
        )
    )

    assert response.payload["status"] == "completed"
    assert captured["url"] == "http://agentgateway:8090/v1/responses"
    assert captured["body"] == {
        "model": "default",
        "input": "What time is it?",
        "metadata": {"turn_id": "turn-1"},
        "instructions": "Use the time tool.",
        "max_output_tokens": 128,
        "tool_choice": "auto",
        "tools": [
            {
                "type": "function",
                "name": "demo_time-get_current_time",
                "description": "Return the current time.",
                "parameters": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        ],
    }
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-request-id"] == TRACE_ID
    assert str(headers["traceparent"]).startswith(f"00-{TRACE_ID}-")
    assert "x-bf-session-id" not in headers
    assert "x-bf-mcp-include-tools" not in headers


@pytest.mark.asyncio
async def test_agentgateway_model_adapter_normalizes_semantic_sse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "text/event-stream"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                'event: response.created\n'
                'data: {"type":"response.created"}\n\n'
                'event: response.output_text.delta\n'
                'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    gateway = AgentgatewayModelGateway(
        "http://agentgateway:8090",
        timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    events = [
        event
        async for event in gateway.stream(
            ModelRequest(model="default", input="hello", correlation_id=TRACE_ID)
        )
    ]

    assert [event.type for event in events] == [
        "response.created",
        "response.output_text.delta",
    ]
    assert events[-1].delta == "hello"


@pytest.mark.asyncio
async def test_agentgateway_model_adapter_requires_explicit_tool_definitions() -> None:
    gateway = AgentgatewayModelGateway(
        "http://agentgateway:8090",
        timeout_seconds=30,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
    )
    with pytest.raises(GatewayProtocolError, match="model_tool_definitions_missing"):
        await gateway.respond(
            ModelRequest(
                model="default",
                input="hello",
                correlation_id=TRACE_ID,
                tools=("demo_time-get_current_time",),
                tool_choice="auto",
            )
        )


@pytest.mark.asyncio
async def test_agentgateway_tool_adapter_maps_names_and_mcp_envelopes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-1"},
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
                },
            )
        if body["method"] == "notifications/initialized":
            assert request.headers["mcp-session-id"] == "session-1"
            return httpx.Response(202)
        if body["method"] == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "time_get_current_time",
                        "description": "Current time",
                        "inputSchema": {"type": "object"},
                    },
                    {"name": "diagnostic_echo", "inputSchema": {"type": "object"}},
                ]
            }
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
        )

    gateway = AgentgatewayToolGateway(
        "http://agentgateway:8090/",
        transport=httpx.MockTransport(handler),
    )
    definitions = await gateway.list_tools()
    result = await gateway.call_tool(
        ToolCall(
            call_id="call-1",
            name="demo_time-get_current_time",
            arguments={"timezone": "UTC"},
            correlation_id=TRACE_ID,
            max_result_bytes=4096,
        )
    )

    assert [definition.name for definition in definitions] == [
        "demo_time-get_current_time"
    ]
    assert result.payload == {"content": [{"type": "text", "text": "ok"}]}
    assert all(str(request.url) == "http://agentgateway:8090/mcp" for request in requests)
    call_request = requests[-1]
    assert call_request.headers["mcp-session-id"] == "session-1"
    assert json.loads(call_request.content)["params"] == {
        "name": "time_get_current_time",
        "arguments": {"timezone": "UTC"},
    }
    assert str(call_request.headers["traceparent"]).startswith(f"00-{TRACE_ID}-")
    assert "x-bf-mcp-include-tools" not in call_request.headers


@pytest.mark.asyncio
async def test_agentgateway_tool_adapter_accepts_sse_and_enforces_result_bound() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-03-26", "capabilities": {}},
                },
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                'event: message\n'
                f'data: {{"jsonrpc":"2.0","id":"{body["id"]}",'
                '"result":{"content":[{"type":"text","text":"large"}]}}\n\n'
            ),
        )

    gateway = AgentgatewayToolGateway(
        "http://agentgateway:8090",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GatewayProtocolError, match="tool_result_too_large"):
        await gateway.call_tool(
            ToolCall(
                call_id="call-1",
                name="demo_time-get_current_time",
                arguments={"timezone": "UTC"},
                correlation_id=TRACE_ID,
                max_result_bytes=4,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, content=b"not-json"), GatewayProtocolError),
        (
            httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": None, "error": {"code": -32601}},
            ),
            GatewayUpstreamError,
        ),
        (httpx.Response(503, json={"error": "unavailable"}), GatewayUpstreamError),
    ],
)
async def test_agentgateway_tool_adapter_normalizes_failures(
    response: httpx.Response, error: type[Exception]
) -> None:
    gateway = AgentgatewayToolGateway(
        "http://agentgateway:8090",
        transport=httpx.MockTransport(lambda _request: response),
    )
    with pytest.raises(error):
        await gateway.list_tools()


def test_agentgateway_tool_factory_selection() -> None:
    gateway = create_tool_gateway(
        replace(
            settings,
            tool_gateway_url="http://agentgateway:8090",
        )
    )
    assert isinstance(gateway, AgentgatewayToolGateway)


def test_agentgateway_model_factory_selection() -> None:
    gateway = create_model_gateway(
        replace(
            settings,
            model_gateway_url="http://agentgateway:8090",
        )
    )
    assert isinstance(gateway, AgentgatewayModelGateway)
