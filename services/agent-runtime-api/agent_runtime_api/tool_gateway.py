from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx

from agent_runtime_api.auth import RunCapability
from agent_runtime_api.runtime import ToolExecution

MAX_GATEWAY_RESPONSE_BYTES = 16 * 1024
logger = logging.getLogger("uvicorn.error")


class ToolGatewayError(ValueError):
    pass


class McpToolGateway:
    def __init__(
        self,
        client: httpx.AsyncClient,
        mcp_url: str,
        delegation_url: str,
    ) -> None:
        self.client = client
        self.mcp_url = mcp_url.rstrip("/")
        self.delegation_url = delegation_url.rstrip("/")

    async def invoke(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        invocation_id: UUID,
        capability: RunCapability,
    ) -> ToolExecution:
        if capability.delegation_grant_id is None or capability.release_id is None:
            raise ToolGatewayError("tool_delegation_unavailable")
        stage = "delegation_exchange"
        try:
            token_response = await self.client.post(
                f"{self.delegation_url}/v1/delegation-grants/"
                f"{capability.delegation_grant_id}:exchange",
                headers={
                    "X-Run-Capability": f"Bearer {capability.raw_token}",
                    "Idempotency-Key": f"tool-token-{invocation_id}",
                },
                json={
                    "run_id": str(capability.run_id),
                    "attempt_id": str(capability.attempt_id),
                    "lease_epoch": capability.lease_epoch,
                    "audience": "porfirium-mcp-gateway",
                    "scopes": [f"tool:{tool}"],
                },
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = token_payload["access_token"]
            if not isinstance(access_token, str) or not access_token:
                raise ValueError
            stage = "mcp_call"
            response = await self.client.post(
                f"{self.mcp_url}/mcp",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Run-Authorization": f"Bearer {capability.raw_token}",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": str(invocation_id),
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                },
            )
            response.raise_for_status()
            if len(response.content) > MAX_GATEWAY_RESPONSE_BYTES:
                raise ToolGatewayError("tool_response_invalid")
            payload = _mcp_payload(response)
        except ToolGatewayError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            status_code = (
                error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
            )
            logger.warning(
                "tool gateway request failed: stage=%s error_type=%s status_code=%s",
                stage,
                type(error).__name__,
                status_code,
            )
            raise ToolGatewayError("tool_gateway_failed") from None
        if payload.get("error") is not None:
            return ToolExecution(payload["error"], is_error=True)
        if "result" not in payload:
            raise ToolGatewayError("tool_response_invalid")
        return ToolExecution(payload["result"])


def _mcp_payload(response: httpx.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").split(";", 1)[0] == "text/event-stream":
        data = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
        if not data:
            raise ToolGatewayError("tool_response_invalid")
        value = json.loads(data[-1])
    else:
        value = response.json()
    if not isinstance(value, dict):
        raise ToolGatewayError("tool_response_invalid")
    return value
