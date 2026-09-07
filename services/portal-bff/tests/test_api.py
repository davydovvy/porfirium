from __future__ import annotations

import json
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from portal_bff.auth import Identity, get_identity
from portal_bff.main import app

USER_ID = UUID("10000000-0000-0000-0000-000000000001")
CONVERSATION_ID = "20000000-0000-0000-0000-000000000002"
RELEASE_ID = "30000000-0000-0000-0000-000000000003"
RUN_ID = "40000000-0000-0000-0000-000000000004"


def identity() -> Identity:
    return Identity(USER_ID, "alice", "Alice", ("genai-user",), "browser-token")


def configure(monkeypatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    async def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return await handler(request)

    monkeypatch.setenv("CONVERSATION_SERVICE_URL", "http://conversation")
    monkeypatch.setenv("AGENT_REGISTRY_URL", "http://registry")
    monkeypatch.setenv("AGENT_RUNNER_URL", "http://runner")
    monkeypatch.setenv("IDENTITY_DELEGATION_URL", "http://delegation")
    monkeypatch.setenv("OIDC_TOKEN_URL", "http://keycloak/token")
    monkeypatch.setenv("OIDC_CLIENT_ID", "portal-bff")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    app.dependency_overrides[get_identity] = identity
    return requests


def test_catalog_exchanges_browser_token_without_exposing_service_url(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "keycloak":
            form = request.content.decode()
            assert "subject_token=browser-token" in form
            assert "audience=agent-registry" in form
            return httpx.Response(200, json={"access_token": "registry-token"})
        assert request.headers["authorization"] == "Bearer registry-token"
        return httpx.Response(200, json=[{"agent_id": "agent", "default_release_id": RELEASE_ID}])

    requests = configure(monkeypatch, handler)
    response = TestClient(app).get("/api/v1/agents")

    assert response.status_code == 200
    assert response.json()[0]["default_release_id"] == RELEASE_ID
    assert [request.url.host for request in requests] == ["keycloak", "registry"]
    assert "registry" not in response.text


def test_conversation_identity_and_thread_are_server_owned(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.headers["x-user-id"] == str(USER_ID)
        assert request.headers["idempotency-key"] == "create-123"
        assert payload["release_id"] == RELEASE_ID
        assert UUID(payload["thread_id"])
        return httpx.Response(201, json={"conversation_id": CONVERSATION_ID, **payload})

    configure(monkeypatch, handler)
    response = TestClient(app).post(
        "/api/v1/conversations",
        headers={"Idempotency-Key": "create-123"},
        json={"title": "Fresh", "release_id": RELEASE_ID},
    )

    assert response.status_code == 201
    assert response.json()["conversation_id"] == CONVERSATION_ID


def test_message_composes_owned_conversation_and_delegation(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "conversation" and request.method == "GET":
            return httpx.Response(200, json={"release_id": RELEASE_ID, "messages": []})
        if request.url.host == "keycloak":
            return httpx.Response(200, json={"access_token": "registry-token"})
        if request.url.host == "registry":
            assert request.headers["authorization"] == "Bearer registry-token"
            return httpx.Response(
                200,
                json={"manifest": {"spec": {"tools": ["time_get_current_time"]}}},
            )
        if request.url.host == "delegation":
            payload = json.loads(request.content)
            assert payload == {
                "conversation_id": CONVERSATION_ID,
                "release_id": RELEASE_ID,
                "maximum_scopes": ["tool:time_get_current_time"],
            }
            return httpx.Response(201, json={"grant_id": "50000000-0000-0000-0000-000000000005"})
        payload = json.loads(request.content)
        assert payload["content"] == "hello"
        assert UUID(payload["run_id"])
        assert UUID(payload["message_id"])
        return httpx.Response(
            202,
            json={"run_id": payload["run_id"], "conversation_sequence": 1},
        )

    requests = configure(monkeypatch, handler)
    response = TestClient(app).post(
        f"/api/v1/conversations/{CONVERSATION_ID}/messages",
        headers={"Idempotency-Key": "message-123"},
        json={"content": "hello"},
    )

    assert response.status_code == 202
    assert [request.url.host for request in requests] == [
        "conversation", "keycloak", "registry", "delegation", "conversation"
    ]


def test_cancel_rejects_run_not_owned_by_conversation(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [], "input_requests": []})

    requests = configure(monkeypatch, handler)
    response = TestClient(app).post(
        f"/api/v1/conversations/{CONVERSATION_ID}/runs/{RUN_ID}:cancel",
        headers={"Idempotency-Key": "cancel-123"},
    )

    assert response.status_code == 404
    assert [request.url.host for request in requests] == ["conversation"]


def test_projection_recovers_an_active_run_for_sse_reconnect(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "conversation":
            return httpx.Response(
                200,
                json={
                    "conversation_id": CONVERSATION_ID,
                    "messages": [{"run_id": RUN_ID, "role": "user", "status": "completed"}],
                    "last_sequence": 7,
                },
            )
        return httpx.Response(200, json={"run_id": RUN_ID, "state": "running"})

    requests = configure(monkeypatch, handler)
    response = TestClient(app).get(f"/api/v1/conversations/{CONVERSATION_ID}")

    assert response.status_code == 200
    assert response.json()["active_run"] == {"run_id": RUN_ID, "state": "running"}
    assert [request.url.host for request in requests] == ["conversation", "runner"]


def test_projection_does_not_present_cancelled_runner_state_as_active(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "conversation":
            return httpx.Response(
                200,
                json={
                    "conversation_id": CONVERSATION_ID,
                    "messages": [{"run_id": RUN_ID, "role": "user", "status": "completed"}],
                    "last_sequence": 7,
                },
            )
        return httpx.Response(200, json={"run_id": RUN_ID, "state": "cancelled"})

    configure(monkeypatch, handler)
    response = TestClient(app).get(f"/api/v1/conversations/{CONVERSATION_ID}")

    assert response.status_code == 200
    assert "active_run" not in response.json()


def test_sse_forwards_authoritative_replay_cursor(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["last-event-id"] == "41"
        assert request.headers["x-user-id"] == str(USER_ID)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"id: 42\nevent: message.completed\ndata: {}\n\n",
        )

    configure(monkeypatch, handler)
    response = TestClient(app).get(
        f"/api/v1/conversations/{CONVERSATION_ID}/events",
        headers={"Last-Event-ID": "41"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 42" in response.text


def test_publication_requires_role_before_contacting_registry(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected downstream request: {request.url}")

    requests = configure(monkeypatch, handler)
    response = TestClient(app).post(
        "/api/v1/releases",
        headers={"Idempotency-Key": "publish-123"},
        json={"manifest": {}, "image": "registry/image@sha256:digest", "provenance": {}},
    )

    assert response.status_code == 403
    assert requests == []


def test_publication_uses_exchanged_token_and_preserves_evidence(monkeypatch) -> None:
    publisher = Identity(
        USER_ID, "alice", "Alice", ("genai-agent-publisher",), "browser-token"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "keycloak":
            return httpx.Response(200, json={"access_token": "registry-token"})
        assert request.headers["authorization"] == "Bearer registry-token"
        assert request.headers["idempotency-key"] == "publish-123"
        payload = json.loads(request.content)
        assert payload["provenance"]["signature"] == "signed-by-ci"
        return httpx.Response(
            201,
            json={"release_id": RELEASE_ID, "agent_id": "new-agent", "version": "1.0.0"},
        )

    requests = configure(monkeypatch, handler)
    app.dependency_overrides[get_identity] = lambda: publisher
    response = TestClient(app).post(
        "/api/v1/releases",
        headers={"Idempotency-Key": "publish-123"},
        json={
            "manifest": {"kind": "Agent"},
            "image": "registry/image@sha256:digest",
            "provenance": {"signature": "signed-by-ci"},
        },
    )

    assert response.status_code == 201
    assert [request.url.host for request in requests] == ["keycloak", "registry"]
