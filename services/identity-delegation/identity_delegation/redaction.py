from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
TOKEN_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?\b"),
    re.compile(r"(?i)((?:access|refresh|id)_token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
)
SENSITIVE_KEYS = frozenset(
    {"authorization", "access_token", "refresh_token", "id_token", "api_key", "password", "secret"}
)


def redact_text(value: str) -> str:
    result = value
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub(
            lambda match: f"{match.group(1) if match.lastindex else ''}{REDACTED}", result
        )
    return result


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if key.lower() in SENSITIVE_KEYS else redact(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact(child) for child in value]
    if isinstance(value, tuple):
        return tuple(redact(child) for child in value)
    return redact_text(value) if isinstance(value, str) else value
