#!/usr/bin/env python3
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

KEYCLOAK = "https://keycloak.local:8443"
PORTAL = "https://portal.local:8444"
CA_FILE = "/home/dvy/Projects/KeyCloak/certs/contextforge-demo-root-ca.pem"


def request(url: str, *, data: bytes | None = None, token: str | None = None, context=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers), timeout=10, context=context
    ) as response:
        return response.status, json.load(response)


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
    _, payload = request(
        f"{KEYCLOAK}/realms/GenAI-platform/protocol/openid-connect/token",
        data=form,
        context=ssl.create_default_context(cafile=CA_FILE),
    )
    return payload["access_token"]


def main() -> None:
    portal_context = ssl._create_unverified_context()
    status, live = request(f"{PORTAL}/health/live", context=portal_context)
    assert status == 200 and live["status"] == "ok"

    try:
        request(f"{PORTAL}/api/v1/me", context=portal_context)
        raise AssertionError("Protected route accepted an unauthenticated request")
    except urllib.error.HTTPError as error:
        assert error.code == 401

    identities = []
    for username in ("alise", "bob"):
        status, identity = request(
            f"{PORTAL}/api/v1/me", token=token(username), context=portal_context
        )
        assert status == 200
        assert identity["username"] == username
        assert "genai-user" in identity["roles"]
        identities.append(identity["id"])
        print(f"PASS: authenticated {username} with protected identity endpoint")

    assert identities[0] != identities[1]
    print("PASS: unauthenticated access rejected and demo identities are isolated")


if __name__ == "__main__":
    main()
