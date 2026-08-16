from fastapi.testclient import TestClient

from portal_api.main import app

client = TestClient(app)


def test_liveness_is_public() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_config_exposes_no_secrets() -> None:
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["oidc_client_id"] == "genai-demo-web"
    assert "password" not in response.text.lower()


def test_identity_requires_authentication() -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_conversations_require_authentication() -> None:
    assert client.get("/api/v1/conversations").status_code == 401
