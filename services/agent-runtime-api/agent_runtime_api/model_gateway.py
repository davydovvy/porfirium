from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class ModelGatewayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str
    finish_reason: str
    usage: dict[str, Any]


class ModelGateway:
    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def respond(
        self,
        *,
        model: str,
        prompt: str,
        max_output_tokens: int,
        metadata: dict[str, str],
    ) -> ModelResponse:
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/responses",
                json={
                    "model": model,
                    "input": prompt,
                    "max_output_tokens": max_output_tokens,
                    "metadata": metadata,
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = _output_text(payload)
            details = payload.get("response", payload)
            usage = details.get("usage", {}) if isinstance(details, dict) else {}
            finish_reason = (
                str(details.get("status", "completed"))
                if isinstance(details, dict) else "completed"
            )
        except (httpx.HTTPError, TypeError, ValueError) as error:
            raise ModelGatewayError("model gateway request failed") from error
        if (
            not content
            or len(content.encode()) > 12 * 1024
            or not isinstance(usage, dict)
            or len(str(usage).encode()) > 2048
        ):
            raise ModelGatewayError("model gateway response is invalid")
        return ModelResponse(content, finish_reason, usage)


def _output_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    details = payload.get("response", payload)
    output = details.get("output", []) if isinstance(details, dict) else []
    parts: list[str] = []
    for item in output if isinstance(output, list) else []:
        content = item.get("content", []) if isinstance(item, dict) else []
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    if not parts:
        raise ValueError("response contains no output text")
    return "".join(parts)
