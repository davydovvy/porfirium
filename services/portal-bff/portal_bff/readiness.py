from __future__ import annotations

import os

import httpx
from fastapi import HTTPException, status

URL_ENVIRONMENTS = (
    "CONVERSATION_SERVICE_URL",
    "AGENT_REGISTRY_URL",
    "AGENT_RUNNER_URL",
    "IDENTITY_DELEGATION_URL",
)


async def check_dependencies() -> None:
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            for environment in URL_ENVIRONMENTS:
                response = await client.get(f"{os.environ[environment]}/health/ready")
                response.raise_for_status()
    except (KeyError, httpx.HTTPError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dependency unavailable",
        ) from None
