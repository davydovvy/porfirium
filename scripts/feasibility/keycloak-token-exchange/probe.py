#!/usr/bin/env python3
"""Exercise delegated token exchange against a live Keycloak realm."""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class GateFailure(RuntimeError):
    pass


class TokenEndpointFailure(GateFailure):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"token endpoint returned HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _post(url: str, form: dict[str, str], context: ssl.SSLContext) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise TokenEndpointFailure(error.code, detail) from error


def _claims(token: str) -> dict[str, Any]:
    try:
        encoded = token.split(".")[1]
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        return json.loads(payload)
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise GateFailure("Keycloak returned a non-JWT access token") from error


def _audiences(claims: dict[str, Any]) -> set[str]:
    audience = claims.get("aud", [])
    return {audience} if isinstance(audience, str) else set(audience)


def _exchange(
    token_url: str,
    context: ssl.SSLContext,
    *,
    client_id: str,
    client_secret: str,
    subject_token: str,
    audience: str,
    scope: str,
) -> dict[str, Any]:
    return _post(
        token_url,
        {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "client_id": client_id,
            "client_secret": client_secret,
            "subject_token": subject_token,
            "subject_token_type": ACCESS_TOKEN_TYPE,
            "requested_token_type": ACCESS_TOKEN_TYPE,
            "audience": audience,
            "scope": scope,
        },
        context,
    )


def run(args: argparse.Namespace) -> None:
    context = ssl.create_default_context(cafile=args.ca_file)
    token_url = f"{args.issuer.rstrip('/')}/protocol/openid-connect/token"
    logout_url = f"{args.issuer.rstrip('/')}/protocol/openid-connect/logout"
    user_grant = _post(
        token_url,
        {
            "grant_type": "password",
            "client_id": args.user_client_id,
            "username": args.username,
            "password": args.password,
            "scope": f"openid {args.broad_scope}",
        },
        context,
    )
    subject_token = user_grant["access_token"]

    broad = _exchange(
        token_url,
        context,
        client_id=args.delegation_client_id,
        client_secret=args.delegation_client_secret,
        subject_token=subject_token,
        audience=args.mcp_audience,
        scope=args.broad_scope,
    )
    if "refresh_token" in broad:
        raise GateFailure("exchange exposed a refresh token to the attempt")
    broad_claims = _claims(broad["access_token"])
    if _audiences(broad_claims) != {args.mcp_audience}:
        raise GateFailure(f"unexpected exchanged audience: {broad_claims.get('aud')!r}")
    broad_scopes = set(broad_claims.get("scope", "").split())
    requested_broad_scopes = set(args.broad_scope.split())
    if not requested_broad_scopes.issubset(broad_scopes):
        raise GateFailure(f"broad exchange omitted requested scopes: {sorted(broad_scopes)}")

    narrow = _exchange(
        token_url,
        context,
        client_id=args.delegation_client_id,
        client_secret=args.delegation_client_secret,
        subject_token=subject_token,
        audience=args.mcp_audience,
        scope=args.narrow_scope,
    )
    narrow_scopes = set(_claims(narrow["access_token"]).get("scope", "").split())
    requested_narrow_scopes = set(args.narrow_scope.split())
    leaked_scopes = (narrow_scopes & requested_broad_scopes) - requested_narrow_scopes
    if not requested_narrow_scopes.issubset(narrow_scopes) or leaked_scopes:
        raise GateFailure(f"scope was not narrowed: {sorted(narrow_scopes)}")

    renewed = _exchange(
        token_url,
        context,
        client_id=args.delegation_client_id,
        client_secret=args.delegation_client_secret,
        subject_token=subject_token,
        audience=args.mcp_audience,
        scope=args.narrow_scope,
    )
    if "refresh_token" in renewed:
        raise GateFailure("renewal exposed a refresh token to the attempt")

    refresh_token = user_grant.get("refresh_token")
    if not refresh_token:
        raise GateFailure("test user client did not issue the platform-held refresh token")
    _post(
        logout_url,
        {
            "client_id": args.user_client_id,
            "refresh_token": refresh_token,
        },
        context,
    )
    try:
        _exchange(
            token_url,
            context,
            client_id=args.delegation_client_id,
            client_secret=args.delegation_client_secret,
            subject_token=subject_token,
            audience=args.mcp_audience,
            scope=args.narrow_scope,
        )
    except TokenEndpointFailure as error:
        if error.status not in {400, 401}:
            raise GateFailure("logout caused an unexpected exchange failure") from error
        try:
            oauth_error = json.loads(error.detail).get("error")
        except json.JSONDecodeError as decode_error:
            raise GateFailure("logout rejection was not an OAuth error") from decode_error
        invalid_request = oauth_error == "invalid_request" and "Invalid token" in error.detail
        expected_errors = {"invalid_grant", "invalid_token", "not_allowed"}
        if oauth_error not in expected_errors and not invalid_request:
            raise GateFailure(f"unexpected logout rejection: {oauth_error!r}") from error
    else:
        raise GateFailure("token exchange still succeeded after logout")

    print("PASS: audience restriction and scope narrowing")
    print("PASS: renewal without an agent-held refresh token")
    print("PASS: logout blocks subsequent token exchange")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--issuer", required=True)
    result.add_argument("--ca-file")
    result.add_argument("--user-client-id", required=True)
    result.add_argument("--delegation-client-id", required=True)
    result.add_argument("--delegation-client-secret", required=True)
    result.add_argument("--mcp-audience", required=True)
    result.add_argument("--username", required=True)
    result.add_argument("--password", required=True)
    result.add_argument("--broad-scope", default="mcp:catalog:read mcp:time:read")
    result.add_argument("--narrow-scope", default="mcp:time:read")
    return result


if __name__ == "__main__":
    run(parser().parse_args())
