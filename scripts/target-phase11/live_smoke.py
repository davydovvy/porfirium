from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

KEYCLOAK = "http://127.0.0.1:8180/realms/GenAI-platform/protocol/openid-connect/token"
REGISTRY = "http://127.0.0.1:18102"
BFF = "http://127.0.0.1:18100"
CLIENT_ID = "porfirium-target-dev"
CLIENT_SECRET = "dev-target-oidc-client-secret"


def request(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    body: object | None = None,
    form: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    timeout: int = 15,
):
    headers: dict[str, str] = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    elif form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode()
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            content = response.read()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"{method} {url} returned {error.code}: {detail}") from error


def token(form: dict[str, str]) -> str:
    return request(KEYCLOAK, method="POST", form=form)["access_token"]


def subject(access_token: str) -> str:
    import base64

    encoded = access_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))["sub"]


def main() -> None:
    service_token = token({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    user_token = token({
        "grant_type": "password",
        "client_id": "genai-demo-web",
        "username": "Alise",
        "password": "123456",
    })
    user_id = subject(user_token)
    request(
        f"{REGISTRY}/v1/agents/model-only/access-grants",
        method="POST",
        token=service_token,
        idempotency_key="model-only-alise-run",
        body={"subject_type": "user", "subject_id": user_id, "permission": "run"},
    )
    agents = request(f"{BFF}/api/v1/agents", token=user_token)
    model_only = next(item for item in agents if item["agent_id"] == "model-only")
    release_id = model_only["default_release_id"]
    operation = uuid4().hex
    conversation = request(
        f"{BFF}/api/v1/conversations",
        method="POST",
        token=user_token,
        idempotency_key=f"conversation-{operation}",
        body={"title": "Phase 11 live smoke", "release_id": release_id},
    )
    conversation_id = conversation["conversation_id"]
    created = request(
        f"{BFF}/api/v1/conversations/{conversation_id}/messages",
        method="POST",
        token=user_token,
        idempotency_key=f"message-{operation}",
        body={"content": "Reply with exactly: Porfirium model-only smoke passed"},
    )
    run_id = created["run_id"]
    deadline = time.monotonic() + 180
    projection = None
    while time.monotonic() < deadline:
        projection = request(f"{BFF}/api/v1/conversations/{conversation_id}", token=user_token)
        assistant = [item for item in projection["messages"] if item["role"] == "assistant"]
        if assistant and assistant[-1]["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(1)
    else:
        raise RuntimeError("conversation did not reach a terminal assistant message")
    message = assistant[-1]
    if message["status"] != "completed" or not message["content"].strip():
        raise RuntimeError(f"assistant message was not completed: {message['status']}")
    print(f"PASS: authenticated model-only conversation completed for run {run_id}")
    print(f"PASS: assistant returned {len(message['content'].encode())} UTF-8 bytes")


if __name__ == "__main__":
    main()
