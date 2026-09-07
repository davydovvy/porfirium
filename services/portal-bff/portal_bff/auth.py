from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Identity:
    subject: UUID
    username: str
    display_name: str
    roles: tuple[str, ...]
    token: str


async def get_identity(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    token = credentials.credentials
    if not token.isascii() or len(token) > 8192:
        raise HTTPException(status_code=401, detail="Invalid access token")
    try:
        response = await request.app.state.client.post(
            os.environ["OIDC_INTROSPECTION_URL"],
            data={"token": token, "token_type_hint": "access_token"},
            auth=(os.environ["OIDC_CLIENT_ID"], os.environ["OIDC_CLIENT_SECRET"]),
        )
        response.raise_for_status()
        claims: dict[str, Any] = response.json()
        audiences = claims.get("aud", [])
        if isinstance(audiences, str):
            audiences = [audiences]
        required_audience = os.environ.get("OIDC_AUDIENCE", "genai-demo-api")
        if claims.get("active") is not True or required_audience not in audiences:
            raise ValueError("inactive token")
        subject = UUID(claims["sub"])
    except (KeyError, TypeError, ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from error
    roles = claims.get("realm_access", {}).get("roles", [])
    if not isinstance(roles, list):
        roles = []
    return Identity(
        subject=subject,
        username=str(claims.get("preferred_username", subject)),
        display_name=str(claims.get("name", claims.get("preferred_username", "User"))),
        roles=tuple(role for role in roles if isinstance(role, str)),
        token=token,
    )


CurrentIdentity = Annotated[Identity, Depends(get_identity)]
