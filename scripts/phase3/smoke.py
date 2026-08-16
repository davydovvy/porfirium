#!/usr/bin/env python3
import json
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

KEYCLOAK = "https://keycloak.local:8443"
PORTAL = "https://portal.local:8444"
CA_FILE = "/home/dvy/Projects/KeyCloak/certs/contextforge-demo-root-ca.pem"
PORTAL_CONTEXT = ssl._create_unverified_context()


def request(path: str, token: str, *, method: str = "GET", body: object | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(
        urllib.request.Request(f"{PORTAL}{path}", data=data, headers=headers, method=method),
        timeout=180, context=PORTAL_CONTEXT,
    ) as response:
        return response.status, json.load(response)


def token(username: str) -> str:
    form = urllib.parse.urlencode({
        "grant_type": "password", "client_id": "genai-demo-web",
        "scope": "openid profile email roles", "username": username, "password": "123456",
    }).encode()
    with urllib.request.urlopen(
        urllib.request.Request(
            f"{KEYCLOAK}/realms/GenAI-platform/protocol/openid-connect/token", data=form
        ), timeout=15, context=ssl.create_default_context(cafile=CA_FILE),
    ) as response:
        return json.load(response)["access_token"]


def stream_with_restart(path: str, access_token: str) -> list[dict[str, object]]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "text/event-stream"}
    events: list[dict[str, object]] = []
    restarted = False
    with urllib.request.urlopen(
        urllib.request.Request(f"{PORTAL}{path}", headers=headers),
        timeout=180, context=PORTAL_CONTEXT,
    ) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            events.append(event)
            if event["type"] == "agent.status" and not restarted:
                subprocess.run(["docker", "compose", "restart", "agent-worker"], check=True)
                restarted = True
    assert restarted
    return events


def main() -> None:
    access_token = token("alise")
    _, conversation = request(
        "/api/v1/conversations", access_token, method="POST",
        body={"title": "Phase 3 durable recovery", "mode": "agent"},
    )
    key = f"phase3-{uuid.uuid4()}"
    _, turn = request(
        f"/api/v1/conversations/{conversation['id']}/turns", access_token, method="POST",
        body={"content": "Reply with exactly: phase3-agent-ok", "idempotency_key": key},
    )
    events = stream_with_restart(turn["events_url"], access_token)
    types = [event["type"] for event in events]
    assert types[0] == "turn.accepted"
    assert types[-1] == "turn.completed"
    statuses = [event["payload"]["status"] for event in events if event["type"] == "agent.status"]
    assert statuses == ["planning", "generating", "completed"]
    _, restored = request(f"/api/v1/conversations/{conversation['id']}", access_token)
    assert restored["active_turn"] is None
    assert restored["messages"][-1]["content"].strip() == "phase3-agent-ok"
    time.sleep(1)
    subprocess.run(
        ["docker", "compose", "exec", "-T", "temporal", "temporal", "workflow", "show",
         "--workflow-id", f"porfirium-agent-{turn['turn_id']}", "--address", "temporal:7233"],
        check=True, stdout=subprocess.DEVNULL,
    )
    print("PASS: durable Agent emitted ordered planning, generation, and completion status")
    print("PASS: Agent completed after its Temporal worker was restarted mid-run")
    print("PASS: final response persisted and the Temporal workflow is inspectable")


if __name__ == "__main__":
    main()
