from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any


def issue_run_capability(claims: dict[str, Any], secret: str, deadline: datetime) -> str:
    payload = {
        **claims,
        "audience": "agent-runtime-api",
        "operations": ["runtime:connect"],
        "deadline": int(deadline.timestamp()),
        "exp": int(deadline.timestamp()),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    ).rstrip(b"=")
    return f"{encoded.decode()}.{signature.decode()}"

