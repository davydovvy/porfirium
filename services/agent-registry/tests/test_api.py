from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import agent_registry.main as registry_main
from agent_registry.auth import ServiceIdentity, require_publisher
from agent_registry.main import app
from agent_registry.publication import PublishedRelease

DIGEST = "sha256:" + "a" * 64
IMAGE = f"registry.local/example-agent@{DIGEST}"
BODY = {
    "manifest": {
        "apiVersion": "porfirium.ai/v1",
        "kind": "Agent",
        "metadata": {"name": "example-agent", "version": "1.0.0"},
        "spec": {
            "image": IMAGE,
            "entrypoint": "example_agent.main:graph",
            "sdk": ">=1.0,<2.0",
            "models": ["default"],
            "tools": [],
            "configSchema": {},
            "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
        },
    },
    "image": IMAGE,
    "provenance": {
        "subjectDigest": DIGEST,
        "signature": "c2lnbmF0dXJl",
        "keyId": "ci-key",
    },
}


class AcceptEvidence:
    async def verify(self, release: object) -> None:
        return None


class NonPublisherAuthenticator:
    async def authenticate(self, token: str) -> ServiceIdentity:
        return ServiceIdentity("service-account-reader", "portal-bff", frozenset())


def test_requires_bearer_authentication() -> None:
    app.dependency_overrides.pop(require_publisher, None)
    client = TestClient(app)

    response = client.post("/v1/releases", headers={"Idempotency-Key": "publish-1234"}, json=BODY)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "authentication_required"
    assert response.json()["retryable"] is False


def test_requires_publisher_role() -> None:
    app.dependency_overrides.pop(require_publisher, None)
    app.state.authenticator = NonPublisherAuthenticator()
    client = TestClient(app)

    response = client.post(
        "/v1/releases",
        headers={"Authorization": "Bearer opaque-token", "Idempotency-Key": "publish-1234"},
        json=BODY,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "publication_forbidden"


def test_publishes_contract_response_with_verified_identity(monkeypatch: object) -> None:
    identity = ServiceIdentity(
        subject="service-account-publisher",
        client_id="portal-bff",
        roles=frozenset({"genai-agent-publisher"}),
    )
    app.dependency_overrides[require_publisher] = lambda: identity
    app.state.evidence_verifier = AcceptEvidence()
    app.state.pool = object()
    release_id = uuid4()

    async def publish(*args: object, **kwargs: object) -> PublishedRelease:
        assert kwargs["actor_id"] == identity.subject
        assert kwargs["idempotency_key"] == "publish-1234"
        return PublishedRelease(release_id, "example-agent", "1.0.0", IMAGE, BODY["manifest"])

    monkeypatch.setattr(registry_main, "publish_release", publish)  # type: ignore[attr-defined]
    client = TestClient(app)

    response = client.post(
        "/v1/releases",
        headers={"Idempotency-Key": "publish-1234"},
        json=BODY,
    )

    assert response.status_code == 201
    assert response.json() == {
        "release_id": str(release_id),
        "agent_id": "example-agent",
        "version": "1.0.0",
        "image": IMAGE,
        "manifest": BODY["manifest"],
        "status": "published",
    }
    app.dependency_overrides.pop(require_publisher, None)


def test_gets_visible_release_by_opaque_release_id(monkeypatch: object) -> None:
    identity = ServiceIdentity("user", "portal-bff", frozenset())
    app.dependency_overrides[registry_main.authenticated_identity] = lambda: identity
    app.state.pool = object()
    release_id = uuid4()

    async def get_release(*args: object) -> PublishedRelease:
        assert args == (app.state.pool, identity, release_id)
        return PublishedRelease(release_id, "example-agent", "1.0.0", IMAGE, BODY["manifest"])

    monkeypatch.setattr(registry_main, "get_visible_release_by_id", get_release)
    response = TestClient(app).get(f"/v1/releases/{release_id}")

    assert response.status_code == 200
    assert response.json()["release_id"] == str(release_id)
    app.dependency_overrides.pop(registry_main.authenticated_identity, None)


def test_validation_errors_are_bounded_problems() -> None:
    identity = ServiceIdentity("publisher", "portal-bff", frozenset({"genai-agent-publisher"}))
    app.dependency_overrides[require_publisher] = lambda: identity
    client = TestClient(app)
    invalid = {**BODY, "image": "registry.local/example-agent:latest"}

    response = client.post(
        "/v1/releases",
        headers={
            "Idempotency-Key": "publish-1234",
            "X-Correlation-ID": "4cb7bfa4-5c1a-4d64-9e3d-23e44bc45933",
        },
        json=invalid,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "image_invalid"
    assert response.json()["correlation_id"] == "4cb7bfa4-5c1a-4d64-9e3d-23e44bc45933"
    assert "message" not in response.json().get("details", {})
    app.dependency_overrides.pop(require_publisher, None)
