import base64
import json
import logging
import os
from functools import lru_cache

from langfuse import Langfuse

logger = logging.getLogger(__name__)
MAX_TRACE_VALUE_BYTES = 4096


@lru_cache(maxsize=1)
def _client() -> Langfuse | None:
    raw_auth = os.getenv("LANGFUSE_AUTH", "").removeprefix("Basic ")
    if not raw_auth:
        return None
    try:
        public_key, secret_key = base64.b64decode(raw_auth).decode().split(":", 1)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("Langfuse tracing disabled: invalid LANGFUSE_AUTH: %s", type(exc).__name__)
        return None
    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=os.getenv("LANGFUSE_BASE_URL", "http://langfuse-web:3000"),
        flush_at=1,
        additional_headers={"x-langfuse-ingestion-version": "4"},
    )


def _bounded(value: object) -> object:
    encoded = json.dumps(value, separators=(",", ":"), default=str)
    if len(encoded.encode()) <= MAX_TRACE_VALUE_BYTES:
        return value
    return {"truncated": True, "bytes": len(encoded.encode())}


def record_observation(
    *,
    trace_id: str,
    name: str,
    as_type: str,
    input: object,
    output: object,
    metadata: dict[str, object],
    model: str | None = None,
) -> None:
    client = _client()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            trace_context={"trace_id": trace_id, "parent_span_id": trace_id[:16]},
            name=name,
            as_type=as_type,
            input=_bounded(input),
            output=_bounded(output),
            metadata=metadata,
            model=model,
        ):
            pass
        client.flush()
    except Exception:
        logger.exception(
            "Failed to export Langfuse observation trace_id=%s name=%s", trace_id, name
        )
