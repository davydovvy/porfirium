from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg


@dataclass(frozen=True, slots=True)
class Scenario:
    agent_id: str
    version: str
    prompt: str
    tools: tuple[str, ...]


class HttpStatusError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, detail: str) -> None:
        super().__init__(f"{method} {url} returned {status}: {detail}")
        self.status = status


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
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers=headers, method=method),
            timeout=timeout,
        ) as response:
            content = response.read()
            return json.loads(content) if content else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:1000]
        raise HttpStatusError(method, url, error.code, detail) from error


def expect_status(status: int, url: str, **kwargs) -> None:
    try:
        request(url, **kwargs)
    except HttpStatusError as error:
        if error.status == status:
            return
        raise
    raise RuntimeError(f"request unexpectedly succeeded; expected HTTP {status}: {url}")


def token(url: str, form: dict[str, str]) -> str:
    return request(url, method="POST", form=form)["access_token"]


def subject(access_token: str) -> str:
    encoded = access_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))["sub"]


async def verify_tool_records(
    database_url: str, expectations: list[tuple[UUID, Scenario]]
) -> None:
    connection = await asyncpg.connect(database_url, timeout=5)
    try:
        for run_id, scenario in expectations:
            rows = await connection.fetch(
                "SELECT state,is_error,result FROM tool_invocations WHERE run_id=$1",
                run_id,
            )
            if len(rows) != len(scenario.tools):
                raise RuntimeError(
                    f"{scenario.agent_id} recorded {len(rows)} tool invocations; "
                    f"expected {len(scenario.tools)}"
                )
            for row in rows:
                if row["state"] != "completed" or row["is_error"] is not False:
                    raise RuntimeError(
                        f"{scenario.agent_id} tool invocation did not complete successfully"
                    )
                rendered = (
                    row["result"]
                    if isinstance(row["result"], str)
                    else json.dumps(row["result"])
                )
                if "demo-time-mcp" not in rendered:
                    raise RuntimeError("Runtime tool result did not originate from demo-time-mcp")
    finally:
        await connection.close()


async def verify_runtime_schema(database_url: str) -> None:
    connection = await asyncpg.connect(database_url, timeout=5)
    try:
        table = await connection.fetchval(
            "SELECT to_regclass('public.tool_invocations')::text"
        )
    finally:
        await connection.close()
    if table != "tool_invocations":
        raise RuntimeError("Runtime tool_invocations migration has not been applied")


def run_conversation(
    bff_url: str, user_token: str, release_id: str, scenario: Scenario
) -> tuple[UUID, str]:
    operation = uuid4().hex
    conversation = request(
        f"{bff_url}/api/v1/conversations",
        method="POST",
        token=user_token,
        idempotency_key=f"phase12-conversation-{operation}",
        body={"title": f"Phase 12 {scenario.agent_id} acceptance", "release_id": release_id},
    )
    conversation_id = conversation["conversation_id"]
    created = request(
        f"{bff_url}/api/v1/conversations/{conversation_id}/messages",
        method="POST",
        token=user_token,
        idempotency_key=f"phase12-message-{operation}",
        body={"content": scenario.prompt},
    )
    run_id = UUID(created["run_id"])
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        projection = request(f"{bff_url}/api/v1/conversations/{conversation_id}", token=user_token)
        messages = [item for item in projection["messages"] if item["role"] == "assistant"]
        if messages and messages[-1]["status"] in {"completed", "failed", "interrupted"}:
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"{scenario.agent_id} conversation did not complete")
    if messages[-1]["status"] != "completed" or not messages[-1]["content"].strip():
        raise RuntimeError(f"{scenario.agent_id} assistant ended as {messages[-1]['status']}")
    print(f"PASS: {scenario.agent_id} portal conversation completed for run {run_id}")
    return run_id, conversation_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keycloak-token-url", required=True)
    parser.add_argument("--registry-url", required=True)
    parser.add_argument("--bff-url", required=True)
    parser.add_argument("--runtime-database-url", required=True)
    parser.add_argument("--service-client-id", required=True)
    parser.add_argument("--service-client-secret", required=True)
    parser.add_argument("--registry-audience", default="agent-registry")
    parser.add_argument("--user-client-id", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--other-username", required=True)
    parser.add_argument("--other-password", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    service_token = token(
        args.keycloak_token_url,
        {
            "grant_type": "client_credentials",
            "client_id": args.service_client_id,
            "client_secret": args.service_client_secret,
        },
    )
    user_token = token(
        args.keycloak_token_url,
        {
            "grant_type": "password",
            "client_id": args.user_client_id,
            "username": args.username,
            "password": args.password,
        },
    )
    other_user_token = token(
        args.keycloak_token_url,
        {
            "grant_type": "password",
            "client_id": args.user_client_id,
            "username": args.other_username,
            "password": args.other_password,
        },
    )
    if subject(other_user_token) == subject(user_token):
        raise RuntimeError("acceptance users must have different subjects")
    registry_token = token(
        args.keycloak_token_url,
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": args.service_client_id,
            "client_secret": args.service_client_secret,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": args.registry_audience,
        },
    )
    registry_health = request(f"{args.registry_url}/health/ready")
    bff_health = request(f"{args.bff_url}/health/ready")
    if registry_health.get("status") != "ok" or bff_health.get("status") != "ok":
        raise RuntimeError("target Registry or Portal BFF did not report ready")
    asyncio.run(verify_runtime_schema(args.runtime_database_url))
    if args.preflight_only:
        print("PASS: target Registry and Portal BFF dependency graph is ready")
        print("PASS: primary and secondary user credentials resolve to distinct subjects")
        print("PASS: user-to-Registry token exchange is available")
        print("PASS: Runtime database is reachable with the Phase 12 tool migration")
        return
    scenarios = (
        Scenario("model-only", "1.0.0", "Reply with a brief greeting.", ()),
        Scenario(
            "planning-assistant",
            "1.1.0",
            "What is the current time in UTC?",
            ("time_get_current_time",),
        ),
    )
    user_id = subject(user_token)
    for scenario in scenarios:
        request(
            f"{args.registry_url}/v1/agents/{scenario.agent_id}/access-grants",
            method="POST",
            token=service_token,
            idempotency_key=f"phase12-{scenario.agent_id}-access-{user_id}",
            body={"subject_type": "user", "subject_id": user_id, "permission": "run"},
        )
    agents = request(f"{args.bff_url}/api/v1/agents", token=user_token)
    expectations: list[tuple[UUID, Scenario]] = []
    owned_runs: list[tuple[UUID, str]] = []
    for scenario in scenarios:
        agent = next((item for item in agents if item["agent_id"] == scenario.agent_id), None)
        if agent is None or not agent.get("default_release_id"):
            raise RuntimeError(f"{scenario.agent_id} has no visible default release")
        release_id = agent["default_release_id"]
        release = request(f"{args.registry_url}/v1/releases/{release_id}", token=registry_token)
        manifest = release["manifest"]["spec"]
        if (
            release["version"] != scenario.version
            or manifest["models"] != ["default"]
            or tuple(manifest["tools"]) != scenario.tools
        ):
            raise RuntimeError(f"{scenario.agent_id} default is not the expected release")
        run_id, conversation_id = run_conversation(
            args.bff_url, user_token, release_id, scenario
        )
        expectations.append((run_id, scenario))
        owned_runs.append((run_id, conversation_id))

    protected_run_id, protected_conversation_id = owned_runs[0]
    expect_status(
        404,
        f"{args.bff_url}/api/v1/conversations/{protected_conversation_id}",
        token=other_user_token,
    )
    expect_status(
        404,
        f"{args.bff_url}/api/v1/conversations/{protected_conversation_id}/runs/"
        f"{protected_run_id}:cancel",
        method="POST",
        token=other_user_token,
        idempotency_key=f"phase12-foreign-cancel-{uuid4().hex}",
    )
    expect_status(
        422,
        f"{args.bff_url}/api/v1/conversations",
        method="POST",
        token=user_token,
        idempotency_key=f"phase12-malformed-{uuid4().hex}",
        body={"title": "invalid", "release_id": str(uuid4()), "unexpected": True},
    )
    print("PASS: foreign conversation read and cancellation are hidden")
    print("PASS: malformed portal request is rejected at the boundary")

    asyncio.run(verify_tool_records(args.runtime_database_url, expectations))
    print("PASS: model-only recorded no tool invocations")
    print("PASS: planning-assistant recorded one successful result from demo-time-mcp")
    print("PASS: complete two-agent live matrix")


if __name__ == "__main__":
    main()
