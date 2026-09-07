import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from agent_runtime_api.model_gateway import ModelGateway, ModelGatewayError
from agent_runtime_api.proto import runtime_pb2 as pb
from agent_runtime_api.runtime import RuntimeService, ToolExecution


class ToolConnection:
    def __init__(self, existing=None) -> None:
        self.existing = existing

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def transaction(self):
        return self

    async def fetchrow(self, *args):
        return self.existing

    async def execute(self, query, *args):
        return "UPDATE 1" if query.startswith("UPDATE") else "OK"


class ToolPool:
    def __init__(self, existing=None) -> None:
        self.connection = ToolConnection(existing)

    def acquire(self):
        return self.connection


@pytest.mark.asyncio
async def test_gateway_extracts_bounded_responses_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers.get("authorization") is None
        body = json.loads(request.content)
        assert body["model"] == "default"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": "hello"}]}],
                "usage": {"output_tokens": 1},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelGateway(client, "http://gateway").respond(
            model="default", prompt="hi", max_output_tokens=32, metadata={"run_id": "run"}
        )

    assert result.content == "hello"
    assert result.usage == {"output_tokens": 1}


@pytest.mark.asyncio
async def test_runtime_denies_model_outside_signed_grant() -> None:
    gateway = SimpleNamespace(respond=None)
    service = RuntimeService(SimpleNamespace(), gateway)
    capability = SimpleNamespace(models=("default",), run_id=uuid4(), user_id=uuid4())

    with pytest.raises(ValueError, match="model_forbidden"):
        await service._call_model(
            capability,
            pb.ModelCall(
                request_id=str(uuid4()), model="ungranted", prompt="hello", max_output_tokens=32
            ),
        )


@pytest.mark.asyncio
async def test_gateway_rejects_oversized_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "x" * (12 * 1024 + 1)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelGatewayError):
            await ModelGateway(client, "http://gateway").respond(
                model="default", prompt="hi", max_output_tokens=32, metadata={}
            )


@pytest.mark.asyncio
async def test_runtime_denies_tool_outside_signed_grant() -> None:
    service = RuntimeService(SimpleNamespace(), tool_gateway=SimpleNamespace())
    capability = SimpleNamespace(tools=("time.current",))

    with pytest.raises(ValueError, match="tool_forbidden"):
        await service._call_tool(
            capability,
            pb.ToolCall(invocation_id=str(uuid4()), tool="diagnostic.echo"),
        )


@pytest.mark.asyncio
async def test_runtime_fails_closed_without_delegated_gateway() -> None:
    service = RuntimeService(SimpleNamespace())
    capability = SimpleNamespace(tools=("time.current",))

    with pytest.raises(ValueError, match="tool_delegation_unavailable"):
        await service._call_tool(
            capability,
            pb.ToolCall(invocation_id=str(uuid4()), tool="time.current"),
        )


@pytest.mark.asyncio
async def test_runtime_invokes_delegated_gateway_for_granted_tool() -> None:
    class Gateway:
        async def invoke(self, **kwargs):
            assert kwargs["tool"] == "time.current"
            assert kwargs["arguments"] == {"zone": "UTC"}
            return ToolExecution({"hour": 12})

    service = RuntimeService(ToolPool(), tool_gateway=Gateway())
    capability = SimpleNamespace(
        tools=("time.current",), run_id=uuid4(), attempt_id=uuid4(), lease_epoch=1
    )
    call = pb.ToolCall(invocation_id=str(uuid4()), tool="time.current")
    call.arguments.update({"zone": "UTC"})

    result = await service._call_tool(capability, call)

    assert result == ToolExecution({"hour": 12})


@pytest.mark.asyncio
async def test_runtime_never_reexecutes_ambiguous_tool_invocation() -> None:
    class Gateway:
        async def invoke(self, **kwargs):
            raise AssertionError("ambiguous invocation must not be called again")

    call = pb.ToolCall(invocation_id=str(uuid4()), tool="time.current")
    capability = SimpleNamespace(
        tools=("time.current",), run_id=uuid4(), attempt_id=uuid4(), lease_epoch=1
    )
    request_digest = hashlib.sha256(
        b'{"arguments":{},"tool":"time.current"}'
    ).hexdigest()
    service = RuntimeService(
        ToolPool({"request_sha256": request_digest, "state": "executing",
                  "result": None, "is_error": None}),
        tool_gateway=Gateway(),
    )

    with pytest.raises(ValueError, match="tool_outcome_ambiguous"):
        await service._call_tool(capability, call)


@pytest.mark.asyncio
async def test_runtime_replays_completed_tool_result_without_gateway_call() -> None:
    class Gateway:
        async def invoke(self, **kwargs):
            raise AssertionError("completed invocation must be replayed")

    call = pb.ToolCall(invocation_id=str(uuid4()), tool="time.current")
    capability = SimpleNamespace(
        tools=("time.current",), run_id=uuid4(), attempt_id=uuid4(), lease_epoch=1
    )
    request_digest = hashlib.sha256(
        b'{"arguments":{},"tool":"time.current"}'
    ).hexdigest()
    service = RuntimeService(
        ToolPool({"request_sha256": request_digest, "state": "completed",
                  "result": '{"hour":12}', "is_error": False}),
        tool_gateway=Gateway(),
    )

    result = await service._call_tool(capability, call)

    assert result == ToolExecution({"hour": 12})
