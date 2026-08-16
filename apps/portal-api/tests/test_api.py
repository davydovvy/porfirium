import pytest
from httpx import ASGITransport, AsyncClient

from portal_api.main import app


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
    assert "password" not in response.text.lower()


async def test_identity_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


async def test_conversations_require_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/conversations")).status_code == 401
