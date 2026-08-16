#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
KEYCLOAK_CA = Path("/home/dvy/Projects/KeyCloak/certs/contextforge-demo-root-ca.pem")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: object | None = None,
    headers: dict[str, str] | None = None,
    context: ssl.SSLContext | None = None,
    timeout: float = 120,
) -> object:
    data = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.load(response)


def request_sse(
    url: str,
    *,
    body: object,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
) -> list[dict[str, object]]:
    data = json.dumps(body).encode()
    request_headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    events: list[dict[str, object]] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        assert response.headers.get_content_type() == "text/event-stream"
        for raw_line in response:
            line = raw_line.decode().strip()
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if payload and payload != "[DONE]":
                event = json.loads(payload)
                assert isinstance(event, dict)
                events.append(event)
    return events


def response_text(response: object) -> str:
    assert isinstance(response, dict)
    texts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                texts.append(str(part.get("text", "")))
    return "".join(texts)


def function_call(response: object, expected_name: str) -> dict[str, object]:
    assert isinstance(response, dict)
    calls = [
        item
        for item in response.get("output", [])
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == expected_name
    ]
    assert len(calls) == 1
    return calls[0]


def check(name: str, action) -> object:
    try:
        result = action()
    except Exception as exc:
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        raise
    print(f"PASS {name}")
    return result


def main() -> int:
    local_env = read_env(ROOT / ".env")

    keycloak_context = ssl.create_default_context(cafile=str(KEYCLOAK_CA))
    keycloak = check(
        "Keycloak canonical HTTPS discovery",
        lambda: request_json(
            "https://keycloak.local:8443/realms/master/.well-known/openid-configuration",
            context=keycloak_context,
        ),
    )
    assert isinstance(keycloak, dict) and keycloak["issuer"].startswith("https://keycloak.local:8443/")

    check("diagnostic MCP health", lambda: request_json("http://127.0.0.1:8091/health"))
    check("Langfuse health", lambda: request_json("http://127.0.0.1:3000/api/public/health"))
    check("Bifrost health", lambda: request_json("http://127.0.0.1:8088/health"))
    live_config = check(
        "Bifrost automatic MCP injection disabled",
        lambda: request_json("http://127.0.0.1:8088/api/config"),
    )
    assert isinstance(live_config, dict)
    assert live_config.get("client_config", {}).get("mcp_disable_auto_tool_inject") is True

    clients = check(
        "Bifrost discovered diagnostic MCP server",
        lambda: request_json("http://127.0.0.1:8088/api/mcp/clients"),
    )
    client_items = clients.get("clients", []) if isinstance(clients, dict) else []
    matching_clients = [
        item
        for item in client_items
        if item.get("config", {}).get("name") == "phase0_diagnostic"
    ]
    assert len(matching_clients) == 1
    assert matching_clients[0].get("state") == "connected"
    tool_names = {
        tool.get("name")
        for tool in matching_clients[0].get("tools", [])
        if isinstance(tool, dict)
    }
    assert {"echo", "platform_info"}.issubset(tool_names)

    tool_result = check(
        "read-only MCP tool execution through Bifrost",
        lambda: request_json(
            "http://127.0.0.1:8088/v1/mcp/tool/execute",
            method="POST",
            headers={"x-bf-mcp-include-tools": "phase0_diagnostic-echo"},
            body={
                "id": "phase0-smoke-tool",
                "type": "function",
                "function": {
                    "name": "phase0_diagnostic-echo",
                    "arguments": json.dumps({"message": "phase0-mcp-ok"}),
                },
            },
        ),
    )
    assert "phase0-mcp-ok" in json.dumps(tool_result)

    if os.environ.get("PHASE0_SKIP_YANDEX") == "1":
        print("SKIP Yandex completion/tool-call checks (PHASE0_SKIP_YANDEX=1)")
    else:
        model = local_env["YANDEX_MODEL"]
        responses_url = "http://127.0.0.1:8088/v1/responses"
        completion = check(
            "Yandex Responses API through Bifrost",
            lambda: request_json(
                responses_url,
                method="POST",
                body={
                    "model": f"yandex/{model}",
                    "input": "Reply with exactly: phase0-responses-ok",
                    "max_output_tokens": 256,
                },
            ),
        )
        assert completion.get("status") == "completed"
        assert completion.get("tools") == []
        assert response_text(completion).strip() == "phase0-responses-ok"

        stream_events = check(
            "Yandex Responses API semantic streaming through Bifrost",
            lambda: request_sse(
                responses_url,
                body={
                    "model": f"yandex/{model}",
                    "input": "Reply with exactly: phase0-stream-ok",
                    "max_output_tokens": 256,
                    "stream": True,
                },
            ),
        )
        event_types = [event.get("type") for event in stream_events]
        assert "response.created" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.completed" in event_types
        streamed_text = "".join(
            str(event.get("delta", ""))
            for event in stream_events
            if event.get("type") == "response.output_text.delta"
        )
        assert streamed_text.strip() == "phase0-stream-ok"

        structured = check(
            "Yandex Responses API JSON Schema output through Bifrost",
            lambda: request_json(
                responses_url,
                method="POST",
                body={
                    "model": f"yandex/{model}",
                    "input": "Return status ok.",
                    "max_output_tokens": 256,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "phase0_status",
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "const": "ok"}},
                                "required": ["status"],
                                "additionalProperties": False,
                            },
                            "strict": True,
                        },
                    },
                },
            ),
        )
        assert json.loads(response_text(structured))["status"] == "ok"

        tool_name = "phase0_diagnostic-echo"
        tool_prompt = "Call the echo tool with message phase0-tool-ok."
        forced = check(
            "Yandex Responses API forced MCP tool call through Bifrost",
            lambda: request_json(
                responses_url,
                method="POST",
                headers={"x-bf-mcp-include-tools": tool_name},
                body={
                    "model": f"yandex/{model}",
                    "input": tool_prompt,
                    "max_output_tokens": 256,
                    "tool_choice": {"type": "function", "name": tool_name},
                },
            ),
        )
        call = function_call(forced, tool_name)
        arguments = json.loads(str(call["arguments"]))
        assert arguments["message"] == "phase0-tool-ok"

        executed = check(
            "Responses API selected MCP tool execution through Bifrost",
            lambda: request_json(
                "http://127.0.0.1:8088/v1/mcp/tool/execute",
                method="POST",
                headers={"x-bf-mcp-include-tools": tool_name},
                body={
                    "id": str(call["call_id"]),
                    "type": "function",
                    "function": {"name": tool_name, "arguments": str(call["arguments"])},
                },
            ),
        )
        assert "phase0-tool-ok" in json.dumps(executed)

        continuation = check(
            "stateless Responses API tool-result continuation through Bifrost",
            lambda: request_json(
                responses_url,
                method="POST",
                body={
                    "model": f"yandex/{model}",
                    "instructions": "After receiving the tool result, reply with exactly: phase0-tool-complete",
                    "input": [
                        {"role": "user", "content": tool_prompt},
                        {
                            "type": "function_call",
                            "call_id": call["call_id"],
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": json.dumps(executed),
                        },
                    ],
                    "max_output_tokens": 256,
                },
            ),
        )
        assert response_text(continuation).strip() == "phase0-tool-complete"

    auth = local_env["LANGFUSE_AUTH"].removeprefix("Basic ")
    decoded = base64.b64decode(auth).decode()
    public_key, secret_key = decoded.split(":", 1)
    observations = check(
        "Langfuse authenticated observations API",
        lambda: request_json(
            "http://127.0.0.1:3000/api/public/observations?limit=10",
            headers={
                "Authorization": "Basic "
                + base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
            },
        ),
    )
    assert isinstance(observations, dict)

    manifest = check(
        "MTG Phase 0 manifest",
        lambda: json.loads((ROOT / "data/mtg/manifest.json").read_text()),
    )
    assert manifest["total_cards"] == 100
    assert sum(item["card_count"] for item in manifest["sets"]) == 100

    print("\nPhase 0 smoke test passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, urllib.error.URLError):
        raise SystemExit(1)
