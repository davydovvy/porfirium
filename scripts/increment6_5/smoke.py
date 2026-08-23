#!/usr/bin/env python3
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

KEYCLOAK = "https://keycloak.local:8443"
PORTAL = "https://portal.local:8444"
CA_FILE = "/home/dvy/Projects/KeyCloak/certs/contextforge-demo-root-ca.pem"
PORTAL_CONTEXT = ssl._create_unverified_context()


def token(username: str) -> str:
    form = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "genai-demo-web",
            "scope": "openid profile email roles",
            "username": username,
            "password": "123456",
        }
    ).encode()
    with urllib.request.urlopen(
        urllib.request.Request(
            f"{KEYCLOAK}/realms/GenAI-platform/protocol/openid-connect/token", data=form
        ),
        timeout=15,
        context=ssl.create_default_context(cafile=CA_FILE),
    ) as response:
        return str(json.load(response)["access_token"])


def request(path: str, access_token: str, *, method: str = "GET", body: object | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(
        urllib.request.Request(f"{PORTAL}{path}", data=data, headers=headers, method=method),
        timeout=30,
        context=PORTAL_CONTEXT,
    ) as response:
        return response.status, json.load(response)


def main() -> None:
    access_token = token("alise")
    _, capabilities = request("/api/v1/capabilities", access_token)
    execution = capabilities["agent_execution"]
    assert execution == {
        "mode": "maintenance",
        "enabled": False,
        "code": "agent_runtime_maintenance",
        "message": "Agent execution is temporarily unavailable while the runtime is upgraded.",
    }, execution

    _, conversation = request(
        "/api/v1/conversations",
        access_token,
        method="POST",
        body={"title": "Increment 6.5 maintenance smoke", "mode": "agent"},
    )
    try:
        request(
            f"/api/v1/conversations/{conversation['id']}/turns",
            access_token,
            method="POST",
            body={
                "content": "This request must not create a turn.",
                "idempotency_key": f"increment6-5-{uuid.uuid4()}",
            },
        )
    except urllib.error.HTTPError as exc:
        assert exc.code == 503, exc.code
        payload = json.load(exc)
        assert payload["detail"]["code"] == "agent_runtime_maintenance", payload
    else:
        raise AssertionError("Agent turn was accepted during runtime maintenance")

    _, projection = request(f"/api/v1/conversations/{conversation['id']}", access_token)
    assert projection["messages"] == [], projection
    assert projection["active_turn"] is None, projection
    print("PASS: Agent maintenance is visible and rejected before turn persistence")


if __name__ == "__main__":
    main()
