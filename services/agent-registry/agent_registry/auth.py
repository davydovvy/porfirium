from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import Depends, Header, Request

from agent_registry.problems import RegistryProblem

PUBLISHER_ROLE = "genai-agent-publisher"
ADMIN_ROLE = "genai-agent-registry-admin"
RESOLVER_ROLE = "genai-agent-run-resolver"


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    subject: str
    client_id: str
    roles: frozenset[str]
    groups: frozenset[str] = frozenset()
    delegated_user_id: str | None = None


class OidcAuthenticator:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        introspection_url: str,
        client_id: str,
        client_secret: str,
        audience: str,
    ) -> None:
        self.client = client
        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.audience = audience

    async def authenticate(self, token: str) -> ServiceIdentity:
        try:
            response = await self.client.post(
                self.introspection_url,
                data={"token": token, "token_type_hint": "access_token"},
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()
            claims: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise RegistryProblem(
                503, "identity_unavailable", "Identity service unavailable", True
            ) from error

        audiences = claims.get("aud", [])
        if isinstance(audiences, str):
            audiences = [audiences]
        if claims.get("active") is not True or self.audience not in audiences:
            raise RegistryProblem(401, "invalid_token", "The access token is invalid")
        subject = claims.get("sub")
        client_id = claims.get("client_id", claims.get("azp"))
        if not isinstance(subject, str) or not subject or not isinstance(client_id, str):
            raise RegistryProblem(401, "invalid_token", "The access token is invalid")
        roles = _roles_from_claims(claims)
        groups = claims.get("groups", [])
        if not isinstance(groups, list) or any(not isinstance(group, str) for group in groups):
            raise RegistryProblem(401, "invalid_token", "The access token is invalid")
        delegated_user_id = claims.get("porfirium_user_id")
        if delegated_user_id is not None and not isinstance(delegated_user_id, str):
            raise RegistryProblem(401, "invalid_token", "The access token is invalid")
        return ServiceIdentity(
            subject=subject,
            client_id=client_id,
            roles=frozenset(roles),
            groups=frozenset(groups),
            delegated_user_id=delegated_user_id,
        )


def _roles_from_claims(claims: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict) and isinstance(realm_access.get("roles"), list):
        roles.update(role for role in realm_access["roles"] if isinstance(role, str))
    direct_roles = claims.get("roles")
    if isinstance(direct_roles, list):
        roles.update(role for role in direct_roles if isinstance(role, str))
    return roles


async def authenticated_identity(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ServiceIdentity:
    if authorization is None or not authorization.startswith("Bearer "):
        raise RegistryProblem(401, "authentication_required", "Authentication is required")
    token = authorization.removeprefix("Bearer ")
    if not token or not token.isascii() or len(token) > 8192:
        raise RegistryProblem(401, "invalid_token", "The access token is invalid")
    authenticator: OidcAuthenticator | None = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        raise RegistryProblem(
            503, "publication_not_configured", "Publication security is not configured"
        )
    return await authenticator.authenticate(token)


async def require_publisher(
    identity: Annotated[ServiceIdentity, Depends(authenticated_identity)],
) -> ServiceIdentity:
    return authorize_publisher(identity)


def authorize_publisher(identity: ServiceIdentity) -> ServiceIdentity:
    if PUBLISHER_ROLE not in identity.roles:
        raise RegistryProblem(403, "publication_forbidden", "Publication is not permitted")
    return identity


def authorize_admin(identity: ServiceIdentity) -> ServiceIdentity:
    if ADMIN_ROLE not in identity.roles:
        raise RegistryProblem(403, "grant_administration_forbidden", "Grant administration denied")
    return identity


async def require_admin(
    identity: Annotated[ServiceIdentity, Depends(authenticated_identity)],
) -> ServiceIdentity:
    return authorize_admin(identity)


async def require_resolver(
    identity: Annotated[ServiceIdentity, Depends(authenticated_identity)],
) -> ServiceIdentity:
    if RESOLVER_ROLE not in identity.roles or identity.delegated_user_id is None:
        raise RegistryProblem(403, "resolution_forbidden", "Run resolution is not permitted")
    return identity
