import asyncio
from uuid import UUID

import httpx
import pytest

from agent_runner.models import RunAdmission
from agent_runner.registry import ClientCredentialsTokenProvider, RegistryResolutionError


def admission() -> RunAdmission:
    return RunAdmission.model_validate({
        "run_id": str(UUID(int=1)),
        "user_id": str(UUID(int=2)),
        "conversation_id": str(UUID(int=3)),
        "thread_id": str(UUID(int=4)),
        "release_id": str(UUID(int=5)),
        "delegation_grant_id": str(UUID(int=6)),
        "trace_id": "a" * 32,
        "trigger": {"type": "user_message", "id": str(UUID(int=7))},
    })


def test_resolution_payload_excludes_execution_only_input() -> None:
    item = admission().model_copy(update={
        "run_input": {
            "trigger_type": "user_message",
            "trigger_id": UUID(int=7),
            "value": "hello",
        }
    })

    assert "trigger" not in item.resolution_payload()
    assert "run_input" not in item.resolution_payload()


def test_client_credentials_token_is_cached_before_renewal() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "resolver-token", "expires_in": 300})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = ClientCredentialsTokenProvider(
                client, "https://id/token", "runner", "secret"
            )
            assert await provider(admission()) == "resolver-token"
            assert await provider(admission()) == "resolver-token"

    asyncio.run(exercise())

    assert len(requests) == 1
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert requests[0].content == b"grant_type=client_credentials"


def test_client_credentials_failure_is_safe() -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(401, json={"error": "denied"})
            )
        ) as client:
            provider = ClientCredentialsTokenProvider(
                client, "https://id/token", "runner", "secret"
            )
            with pytest.raises(RegistryResolutionError, match="token acquisition failed"):
                await provider(admission())

    asyncio.run(exercise())
