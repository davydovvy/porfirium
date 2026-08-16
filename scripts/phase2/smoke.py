#!/usr/bin/env python3
import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

KEYCLOAK = "https://keycloak.local:8443"
PORTAL = "https://portal.local:8444"
CA_FILE = "/home/dvy/Projects/KeyCloak/certs/contextforge-demo-root-ca.pem"
PORTAL_CONTEXT = ssl._create_unverified_context()
ROOT = Path(__file__).resolve().parents[2]


def request(path: str, token: str, *, method: str = "GET", body: object | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    target = path if path.startswith("http") else f"{PORTAL}{path}"
    with urllib.request.urlopen(urllib.request.Request(target, data=data, headers=headers, method=method),
                                timeout=150, context=PORTAL_CONTEXT) as response:
        return response.status, json.load(response)


def token(username: str) -> str:
    form = urllib.parse.urlencode({"grant_type": "password", "client_id": "genai-demo-web",
        "scope": "openid profile email roles", "username": username, "password": "123456"}).encode()
    context = ssl.create_default_context(cafile=CA_FILE)
    with urllib.request.urlopen(urllib.request.Request(
        f"{KEYCLOAK}/realms/GenAI-platform/protocol/openid-connect/token", data=form),
        timeout=15, context=context) as response:
        return json.load(response)["access_token"]


def stream(path: str, access_token: str) -> list[dict[str, object]]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "text/event-stream"}
    events = []
    with urllib.request.urlopen(urllib.request.Request(f"{PORTAL}{path}", headers=headers),
                                timeout=150, context=PORTAL_CONTEXT) as response:
        for raw in response:
            line = raw.decode().strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def trace_observations(trace_id: str) -> list[dict[str, object]]:
    values = dict(
        line.strip().split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    )
    raw_auth = values["LANGFUSE_AUTH"].removeprefix("Basic ")
    public_key, secret_key = base64.b64decode(raw_auth).decode().split(":", 1)
    basic = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    for _ in range(20):
        with urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:3000/api/public/observations?limit=100",
                headers={"Authorization": f"Basic {basic}"},
            ),
            timeout=20,
        ) as response:
            payload = json.load(response)
        matches = [item for item in payload.get("data", []) if item.get("traceId") == trace_id]
        if matches:
            return matches
        time.sleep(0.5)
    return []


def main() -> None:
    alise, bob = token("alise"), token("bob")
    _, conversation = request("/api/v1/conversations", alise, method="POST",
                              body={"title": "Phase 2 smoke", "mode": "direct"})
    conversation_id = conversation["id"]
    key = f"phase2-{uuid.uuid4()}"
    _, turn = request(f"/api/v1/conversations/{conversation_id}/turns", alise, method="POST",
                      body={"content": "Reply with exactly: phase2-direct-ok", "idempotency_key": key})
    _, duplicate = request(f"/api/v1/conversations/{conversation_id}/turns", alise, method="POST",
                           body={"content": "ignored duplicate", "idempotency_key": key})
    assert duplicate["turn_id"] == turn["turn_id"]
    events = stream(turn["events_url"], alise)
    types = [event["type"] for event in events]
    assert types[0] == "turn.accepted" and types[-1] == "turn.completed"
    streamed = "".join(event["payload"].get("delta", "") for event in events
                       if event["type"] == "assistant.delta")
    assert streamed.strip() == "phase2-direct-ok"
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences) and len(sequences) == len(set(sequences))
    replay = stream(f"{turn['events_url']}?after={sequences[-2]}", alise)
    assert len(replay) == 1 and replay[0]["type"] == "turn.completed"
    _, restored = request(f"/api/v1/conversations/{conversation_id}", alise)
    assert [message["role"] for message in restored["messages"]] == ["user", "assistant"]
    assert restored["messages"][-1]["content"].strip() == "phase2-direct-ok"
    observations = trace_observations(turn["correlation_id"])
    assert observations
    assert {item["type"] for item in observations}.issuperset({"GENERATION", "SPAN"})
    try:
        request(f"/api/v1/conversations/{conversation_id}", bob)
        raise AssertionError("Cross-user conversation read succeeded")
    except urllib.error.HTTPError as error:
        assert error.code == 404
    print("PASS: direct Yandex response streamed through Bifrost")
    print("PASS: idempotent turn submission and ordered SSE replay")
    print("PASS: persistent history and cross-user isolation")
    print("PASS: turn correlation ID locates the complete Bifrost trace in Langfuse")


if __name__ == "__main__":
    main()
