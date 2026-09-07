import pytest
from fastapi.testclient import TestClient

from checkpoint_api.main import SERVICE_NAME, SERVICE_VERSION, app
from checkpoint_api.readiness import check_dependencies

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_readiness_dependencies() -> None:
    app.dependency_overrides[check_dependencies] = lambda: None
    yield
    app.dependency_overrides.pop(check_dependencies, None)


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
