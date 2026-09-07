import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from agent_runtime_api.model_gateway import ModelGateway, ModelGatewayError
from agent_runtime_api.proto import runtime_pb2 as pb
from agent_runtime_api.runtime import RuntimeService


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
