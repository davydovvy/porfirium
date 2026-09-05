from fastapi.testclient import TestClient

from agent_registry.main import SERVICE_NAME, SERVICE_VERSION, app
from agent_registry.readiness import check_dependencies

client = TestClient(app)
app.dependency_overrides[check_dependencies] = lambda: None


def test_liveness_contract() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


def test_readiness_contract() -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["service"] == SERVICE_NAME
