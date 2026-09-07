import json
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from agent_runtime_api.auth import RunCapability
from agent_runtime_api.tool_gateway import McpToolGateway, ToolGatewayError


def capability() -> RunCapability:
    return RunCapability(
        user_id=UUID(int=1),
        conversation_id=UUID(int=2),
        thread_id=UUID(int=3),
        run_id=UUID(int=4),
        attempt_id=UUID(int=5),
        lease_epoch=2,
        deadline=9999999999,
        run_input=None,
        starting_checkpoint_id=None,
        models=(),
        trace_id="1" * 32,
        tools=("time_get_current_time",),
        release_id=UUID(int=6),
        delegation_grant_id=UUID(int=7),
        raw_token="signed-run-capability",
    )


@pytest.mark.asyncio
async def test_exchanges_grant_and_calls_mcp_without_persisting_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "delegation":
            assert request.headers["x-run-capability"] == "Bearer signed-run-capability"
            body = json.loads(request.content)
            assert body["scopes"] == ["tool:time_get_current_time"]
            return httpx.Response(200, json={"access_token": "short-lived-user-token"})
        assert request.headers["authorization"] == "Bearer short-lived-user-token"
        assert request.headers["x-run-authorization"] == "Bearer signed-run-capability"
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"content": [{"text": "12:00"}]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await McpToolGateway(
            client, "http://gateway", "http://delegation"
        ).invoke(
            tool="time_get_current_time",
            arguments={"timezone": "UTC"},
            invocation_id=UUID(int=8),
            capability=capability(),
        )

    assert result.result == {"content": [{"text": "12:00"}]}
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_fails_closed_without_attempt_bound_delegation() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ToolGatewayError, match="tool_delegation_unavailable"):
            await McpToolGateway(client, "http://gateway", "http://delegation").invoke(
                tool="time_get_current_time",
                arguments={},
                invocation_id=UUID(int=8),
                capability=replace(capability(), delegation_grant_id=None),
            )
