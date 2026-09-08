from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("uvicorn.error")


class ModelGatewayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str
    finish_reason: str
    usage: dict[str, Any]


class ModelGateway:
    _MAX_ATTEMPTS = 3

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
        request = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "metadata": metadata,
        }
        last_error: Exception | None = None
        for attempt in range(self._MAX_ATTEMPTS):
            try:
                response = await self.client.post(
                    f"{self.base_url}/v1/responses", json=request
                )
                response.raise_for_status()
                payload = response.json()
                content = _output_text(payload)
                if not content:
                    raise ValueError("response contains empty output text")
                details = payload.get("response", payload)
                usage = details.get("usage", {}) if isinstance(details, dict) else {}
                finish_reason = (
                    str(details.get("status", "completed"))
                    if isinstance(details, dict)
                    else "completed"
                )
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                logger.warning(
                    "model gateway attempt failed: attempt=%d error_type=%s status_code=%d",
                    attempt + 1,
                    type(error).__name__,
                    status_code,
                )
                if status_code not in {408, 429} and status_code < 500:
                    raise ModelGatewayError("model gateway request failed") from error
                last_error = error
            except (httpx.RequestError, TypeError, ValueError) as error:
                logger.warning(
                    "model gateway attempt failed: attempt=%d error_type=%s",
                    attempt + 1,
                    type(error).__name__,
                )
                last_error = error
            else:
                if (
                    len(content.encode()) > 12 * 1024
                    or not isinstance(usage, dict)
                    or len(str(usage).encode()) > 2048
                ):
                    logger.warning("model gateway response exceeded bounds")
                    raise ModelGatewayError("model gateway response is invalid")
                return ModelResponse(content, finish_reason, usage)

            if attempt == self._MAX_ATTEMPTS - 1:
                break

        raise ModelGatewayError("model gateway request failed") from last_error


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
