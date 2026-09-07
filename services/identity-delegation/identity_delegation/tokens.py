from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from identity_delegation.problems import DelegationProblem


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(claims: dict[str, Any], secret: str) -> str:
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def verify_token(token: str, secret: str, audience: str) -> dict[str, Any]:
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_decode(signature), expected):
            raise ValueError
        claims = json.loads(_decode(payload))
        if claims.get("aud", claims.get("audience")) != audience or int(
            claims["exp"]
        ) <= int(time.time()):
            raise ValueError
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise DelegationProblem(401, "token_invalid", "Token is invalid") from None
