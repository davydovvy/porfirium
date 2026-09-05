import asyncio

import httpx
import pytest

from agent_registry.auth import OidcAuthenticator
from agent_registry.problems import RegistryProblem


def authenticator(claims: dict[str, object]) -> OidcAuthenticator:
    def introspect(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json=claims)

    client = httpx.AsyncClient(transport=httpx.MockTransport(introspect))
    return OidcAuthenticator(
        client,
        introspection_url="https://identity.local/introspect",
        client_id="agent-registry",
        client_secret="test-secret",
        audience="agent-registry",
    )


def test_accepts_active_audience_scoped_service_token() -> None:
    verifier = authenticator(
        {
            "active": True,
            "sub": "service-account-publisher",
            "client_id": "portal-bff",
            "aud": ["agent-registry"],
            "realm_access": {"roles": ["genai-agent-publisher"]},
        }
    )

    identity = asyncio.run(verifier.authenticate("opaque-token"))

    assert identity.client_id == "portal-bff"
    assert "genai-agent-publisher" in identity.roles


@pytest.mark.parametrize(
    "claims",
    [
        {"active": False, "aud": ["agent-registry"]},
        {"active": True, "sub": "caller", "client_id": "portal-bff", "aud": ["other"]},
    ],
)
def test_rejects_inactive_or_wrong_audience_token(claims: dict[str, object]) -> None:
    verifier = authenticator(claims)

    with pytest.raises(RegistryProblem) as error:
        asyncio.run(verifier.authenticate("opaque-token"))

    assert error.value.code == "invalid_token"
