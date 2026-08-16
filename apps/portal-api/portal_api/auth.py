from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str
    display_name: str
    email: str | None
    roles: tuple[str, ...]


class JwksVerifier:
    def __init__(self) -> None:
        self._jwks: dict[str, Any] | None = None

    async def _load_jwks(self) -> dict[str, Any]:
        verify: bool | str = settings.oidc_ca_file or True
        async with httpx.AsyncClient(verify=verify, timeout=5) as client:
            response = await client.get(settings.jwks_url)
            response.raise_for_status()
            return response.json()

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            if self._jwks is None:
                self._jwks = await self._load_jwks()
            key = next(key for key in self._jwks["keys"] if key["kid"] == header["kid"])
            return jwt.decode(
                token,
                jwt.PyJWK.from_dict(key).key,
                algorithms=["RS256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except (httpx.HTTPError, KeyError, StopIteration, jwt.PyJWTError) as exc:
            self._jwks = None
            raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc


verifier = JwksVerifier()


async def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Identity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    claims = await verifier.verify(credentials.credentials)
    roles = tuple(claims.get("realm_access", {}).get("roles", []))
    if settings.oidc_required_role not in roles:
        raise HTTPException(status_code=403, detail="Required role is missing")
    return Identity(
        subject=claims["sub"],
        username=claims.get("preferred_username", claims["sub"]),
        display_name=claims.get("name", claims.get("preferred_username", "User")),
        email=claims.get("email"),
        roles=roles,
    )


CurrentIdentity = Annotated[Identity, Depends(get_identity)]

