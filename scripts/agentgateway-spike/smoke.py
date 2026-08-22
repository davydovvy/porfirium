#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


GATEWAY = "http://127.0.0.1:8089"
READY = "http://127.0.0.1:15021/healthz/ready"
EXPECTED_TOOLS = {
    "diagnostic_echo",
    "diagnostic_platform_info",
    "time_get_current_time",
    "time_convert_time",
    "mtg-catalog_search_cards",
    "mtg-catalog_get_card",
    "mtg-catalog_compare_cards",
    "mtg-catalog_list_sets",
}


ROOT = Path(__file__).resolve().parents[2]
DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_env() -> dict[str, str]:
    values = {}
    for raw in (ROOT / ".env").read_text().splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key, value = raw.strip().split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def request(path: str, body: object | None = None, *, accept: str = "application/json", headers=None, timeout=180):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": accept, **(headers or {})}
    if data is not None:
        headers["Content-Type"] = "application/json"
    url = path if path.startswith("http://") else f"{GATEWAY}{path}"
    with DIRECT_HTTP.open(
        urllib.request.Request(
            url, data=data, headers=headers,
            method="POST" if data is not None else "GET",
        ),
        timeout=timeout,
    ) as response:
        if response.headers.get_content_type() == "text/event-stream":
            events = []
            for raw in response:
                line = raw.decode().strip()
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    events.append(json.loads(line[5:].strip()))
            return events
        return json.load(response)


def mcp_payload(method: str, params: object | None = None, *, headers=None):
    events = request(
        "/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        accept="application/json, text/event-stream", headers=headers, timeout=10,
    )
    return events[-1] if isinstance(events, list) else events


def mcp(method: str, params: object | None = None, *, headers=None):
    payload = mcp_payload(method, params, headers=headers)
    assert isinstance(payload, dict) and "error" not in payload, payload
    return payload["result"]


def response_text(response: dict) -> str:
    return "".join(
        str(part.get("text", ""))
        for item in response.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def check(name: str, action):
    result = action()
    print(f"PASS {name}")
    return result


def wait_for(name: str, action, predicate, attempts: int = 45):
    last_error = None
    for _ in range(attempts):
        try:
            result = action()
            if predicate(result):
                print(f"PASS {name}")
                return result
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    if last_error:
        raise last_error
    raise AssertionError(f"timed out waiting for {name}")


def tool_names() -> set[str]:
    return {tool["name"] for tool in mcp("tools/list")["tools"]}


def recovered_tool_names() -> set[str]:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "diagnostic-mcp",
            "python",
            "-c",
            (
                "import json,urllib.request;"
                "body=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}).encode();"
                "request=urllib.request.Request('http://agentgateway:8090/mcp',data=body,"
                "headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'});"
                "raw=urllib.request.urlopen(request,timeout=10).read().decode();"
                "print(next(line[5:].strip() for line in raw.splitlines() if line.startswith('data:')))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    payload = json.loads(completed.stdout)
    return {tool["name"] for tool in payload["result"]["tools"]}


def application_network_ready() -> bytes:
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "diagnostic-mcp",
            "python",
            "-c",
            (
                "import urllib.request;"
                "print(urllib.request.urlopen("
                "'http://agentgateway:15021/healthz/ready',timeout=5).read().decode())"
            ),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout.strip()


def denied_tool_payload():
    try:
        return mcp_payload("tools/call", {"name": "diagnostic_not_allowed", "arguments": {}})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        data = next((line[5:].strip() for line in body.splitlines() if line.startswith("data:")), body)
        return json.loads(data)


def completed(body: dict):
    response = request("/v1/responses", body)
    assert isinstance(response, dict) and response.get("status") == "completed", response
    usage = response.get("usage", {})
    assert all(isinstance(usage.get(key), int) for key in ("input_tokens", "output_tokens", "total_tokens"))
    return response


def main() -> None:
    check("Agentgateway readiness", lambda: DIRECT_HTTP.open(READY, timeout=10).read())
    assert check("federated MCP inventory", tool_names) == EXPECTED_TOOLS
    echo = check(
        "MCP tools/call",
        lambda: mcp("tools/call", {"name": "diagnostic_echo", "arguments": {"message": "agentgateway-mcp-ok"}}),
    )
    assert "agentgateway-mcp-ok" in json.dumps(echo)
    denied = check(
        "deny-by-default fabricated MCP tool",
        denied_tool_payload,
    )
    assert "error" in denied

    trace_id = uuid.uuid4().hex
    traced = check(
        "W3C trace propagation",
        lambda: mcp("tools/list", headers={"traceparent": f"00-{trace_id}-0123456789abcdef-01"}),
    )
    assert {tool["name"] for tool in traced["tools"]} == EXPECTED_TOOLS
    auth = read_env()["LANGFUSE_AUTH"]
    wait_for(
        "Agentgateway trace ingestion in Langfuse",
        lambda: request(
            "http://127.0.0.1:3000/api/public/observations?limit=100",
            headers={"Authorization": auth},
        ),
        lambda payload: any(item.get("traceId") == trace_id for item in payload.get("data", [])),
    )

    basic = check(
        "Yandex Responses and usage",
        lambda: completed({
            "model": "default", "input": "Reply with exactly: agentgateway-responses-ok",
            "max_output_tokens": 128,
        }),
    )
    assert response_text(basic).strip() == "agentgateway-responses-ok"

    stream = check(
        "Yandex semantic SSE",
        lambda: request("/v1/responses", {
            "model": "default", "input": "Reply with exactly: agentgateway-stream-ok",
            "max_output_tokens": 128, "stream": True,
        }, accept="text/event-stream"),
    )
    types = {event.get("type") for event in stream}
    assert {"response.created", "response.output_text.delta", "response.completed"} <= types
    assert "".join(str(event.get("delta", "")) for event in stream if event.get("type") == "response.output_text.delta").strip() == "agentgateway-stream-ok"

    structured = check(
        "Yandex strict JSON Schema",
        lambda: completed({
            "model": "default", "input": "Return status ok.", "max_output_tokens": 512,
            "text": {"format": {"type": "json_schema", "name": "status", "strict": True,
                "schema": {"type": "object", "properties": {"status": {"type": "string", "const": "ok"}},
                           "required": ["status"], "additionalProperties": False}}},
        }),
    )
    assert json.loads(response_text(structured)) == {"status": "ok"}

    tool = {"type": "function", "name": "diagnostic_echo", "description": "Return text unchanged.",
            "parameters": {"type": "object", "properties": {"message": {"type": "string"}},
                           "required": ["message"], "additionalProperties": False}, "strict": True}
    forced = check(
        "Yandex forced function call",
        lambda: completed({
            "model": "default", "input": "Call diagnostic_echo with message agentgateway-tool-ok.",
            "tools": [tool], "tool_choice": {"type": "function", "name": "diagnostic_echo"},
            "max_output_tokens": 256,
        }),
    )
    calls = [item for item in forced["output"] if item.get("type") == "function_call"]
    assert len(calls) == 1 and json.loads(calls[0]["arguments"])["message"] == "agentgateway-tool-ok"
    result = check(
        "selected MCP execution",
        lambda: mcp("tools/call", {"name": calls[0]["name"], "arguments": json.loads(calls[0]["arguments"])}),
    )
    continuation = check(
        "stateless function result continuation",
        lambda: completed({
            "model": "default", "instructions": "Reply with exactly: agentgateway-tool-complete",
            "input": [
                {"role": "user", "content": "Call the echo tool."},
                {"type": "function_call", "call_id": calls[0]["call_id"], "name": calls[0]["name"], "arguments": calls[0]["arguments"]},
                {"type": "function_call_output", "call_id": calls[0]["call_id"], "output": json.dumps(result)},
            ], "max_output_tokens": 512,
        }),
    )
    assert response_text(continuation).strip() == "agentgateway-tool-complete", repr(response_text(continuation))

    subprocess.run(["docker", "compose", "restart", "diagnostic-mcp"], check=True, stdout=subprocess.DEVNULL)
    wait_for("MCP recovery after target restart", tool_names, lambda names: names == EXPECTED_TOOLS)
    subprocess.run(["docker", "compose", "restart", "agentgateway"], check=True, stdout=subprocess.DEVNULL)
    wait_for(
        "Agentgateway readiness after restart",
        application_network_ready,
        lambda body: body == b"ready",
        attempts=90,
    )
    wait_for(
        "MCP recovery after gateway restart",
        recovered_tool_names,
        lambda names: names == EXPECTED_TOOLS,
        attempts=90,
    )
    print("\nPASS: pinned Agentgateway/Yandex model and MCP compatibility spike")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, urllib.error.URLError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
