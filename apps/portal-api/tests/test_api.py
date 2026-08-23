from typing import get_type_hints

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from temporalio.converter import default

from portal_api.config import Settings
from portal_api.main import app, require_agent_execution_available
from portal_api.worker import load_agent_run_plan, stored_tool_arguments, tool_rejection_result


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


async def test_liveness_is_public(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_config_exposes_no_secrets(client: AsyncClient) -> None:
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["oidc_client_id"] == "genai-demo-web"
    assert response.json()["agent_execution_mode"] == "maintenance"
    assert "password" not in response.text.lower()


def test_agent_execution_maintenance_gate_is_fail_closed() -> None:
    require_agent_execution_available("direct")
    with pytest.raises(HTTPException) as error:
        require_agent_execution_available("agent")
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "agent_runtime_maintenance"


def test_unknown_agent_execution_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="AGENT_EXECUTION_MODE"):
        Settings(agent_execution_mode="legacy")


def test_generic_activity_input_uses_temporal_json_compatible_hint() -> None:
    hint = get_type_hints(load_agent_run_plan)["value"]
    payload = default().payload_converter.to_payload({"turn_id": "t", "run_snapshot_id": "s"})
    assert payload is not None
    assert default().payload_converter.from_payload(payload, hint) == {
        "turn_id": "t",
        "run_snapshot_id": "s",
    }


def test_tool_rejection_result_is_bounded_and_retryable() -> None:
    assert tool_rejection_result("tool_arguments_schema_invalid") == {
        "error": "tool_arguments_schema_invalid",
        "retryable": True,
    }


def test_empty_allowed_arguments_are_not_marked_rejected() -> None:
    assert stored_tool_arguments(True, {}, "{}") == {}
    assert stored_tool_arguments(False, {}, "{}") == {
        "rejected": True,
        "argument_bytes": 2,
    }


async def test_identity_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


async def test_conversations_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/conversations")).status_code == 401
