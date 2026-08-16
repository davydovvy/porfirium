from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from portal_api.auth import JwksVerifier, get_identity
from portal_api.config import settings


def token_and_jwks(*, roles: list[str]) -> tuple[str, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = "phase1-test"
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "test-subject",
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "preferred_username": "Alise",
            "realm_access": {"roles": roles},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "phase1-test"},
    )
    return token, {"keys": [public_jwk]}


@pytest.mark.asyncio
async def test_verifier_accepts_expected_issuer_and_audience() -> None:
    token, jwks = token_and_jwks(roles=["genai-user"])
    verifier = JwksVerifier()
    verifier._jwks = jwks
    claims = await verifier.verify(token)
    assert claims["sub"] == "test-subject"


@pytest.mark.asyncio
async def test_required_role_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    async def claims(_token: str) -> dict:
        return {
            "sub": "test-subject",
            "preferred_username": "Alise",
            "realm_access": {"roles": []},
        }

    monkeypatch.setattr("portal_api.auth.verifier.verify", claims)
    with pytest.raises(HTTPException) as error:
        await get_identity(HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"))
    assert error.value.status_code == 403
