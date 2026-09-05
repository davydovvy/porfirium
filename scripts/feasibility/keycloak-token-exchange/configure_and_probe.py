#!/usr/bin/env python3
"""Configure a disposable exchange client, then run the live gate without storing its secret."""

from __future__ import annotations

import argparse
import importlib.util
import json
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any


def _request(
    url: str,
    context: ssl.SSLContext,
    *,
    method: str = "GET",
    token: str | None = None,
    body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
) -> Any:
    headers: dict[str, str] = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    elif form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Keycloak admin API returned HTTP {error.code}: {detail}") from error


def _one(items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    if len(items) != 1:
        raise RuntimeError(f"expected exactly one {kind}, found {len(items)}")
    return items[0]


def _load_probe() -> ModuleType:
    path = Path(__file__).with_name("probe.py")
    spec = importlib.util.spec_from_file_location("keycloak_exchange_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the token-exchange probe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(admin_url: str, context: ssl.SSLContext, token: str, client_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"clientId": client_id})
    return _one(_request(f"{admin_url}/clients?{query}", context, token=token), client_id)


def run(args: argparse.Namespace) -> None:
    context = ssl.create_default_context(cafile=args.ca_file)
    base_url, realm = args.issuer.rsplit("/realms/", 1)

    def admin_token() -> str:
        return _request(
            f"{base_url}/realms/master/protocol/openid-connect/token",
            context,
            method="POST",
            form={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": args.admin_username,
                "password": args.admin_password,
            },
        )["access_token"]

    master_token = admin_token()
    admin_url = f"{base_url}/admin/realms/{urllib.parse.quote(realm)}"

    scopes = _request(f"{admin_url}/client-scopes", context, token=master_token)
    scope_ids: dict[str, str] = {}
    for scope_name in args.broad_scope.split():
        matches = [scope for scope in scopes if scope["name"] == scope_name]
        if not matches:
            _request(
                f"{admin_url}/client-scopes",
                context,
                method="POST",
                token=master_token,
                body={
                    "name": scope_name,
                    "protocol": "openid-connect",
                    "attributes": {"include.in.token.scope": "true"},
                },
            )
            scopes = _request(f"{admin_url}/client-scopes", context, token=master_token)
            matches = [scope for scope in scopes if scope["name"] == scope_name]
        scope_ids[scope_name] = _one(matches, f"client scope {scope_name}")["id"]

    master_token = admin_token()
    existing = _request(
        f"{admin_url}/clients?{urllib.parse.urlencode({'clientId': args.mcp_audience})}",
        context,
        token=master_token,
    )
    if not existing:
        _request(
            f"{admin_url}/clients",
            context,
            method="POST",
            token=master_token,
            body={
                "clientId": args.mcp_audience,
                "name": "Porfirium MCP Gateway",
                "enabled": True,
                "bearerOnly": True,
                "protocol": "openid-connect",
            },
        )

    client_secret = secrets.token_urlsafe(32)
    existing = _request(
        f"{admin_url}/clients?{urllib.parse.urlencode({'clientId': args.delegation_client_id})}",
        context,
        token=master_token,
    )
    representation = {
        "clientId": args.delegation_client_id,
        "name": "Porfirium Identity Delegation feasibility client",
        "enabled": True,
        "publicClient": False,
        "bearerOnly": False,
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "protocol": "openid-connect",
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "attributes": {
            "standard.token.exchange.enabled": "true",
            "standard.token.exchange.enableRefreshRequestedTokenType": "false",
        },
        "protocolMappers": [
            {
                "name": "mcp-gateway-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": args.mcp_audience,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            }
        ],
    }
    if existing:
        client_uuid = _one(existing, args.delegation_client_id)["id"]
        representation["id"] = client_uuid
        _request(
            f"{admin_url}/clients/{client_uuid}",
            context,
            method="PUT",
            token=master_token,
            body=representation,
        )
    else:
        _request(
            f"{admin_url}/clients",
            context,
            method="POST",
            token=master_token,
            body=representation,
        )
        client_uuid = _client(
            admin_url, context, master_token, args.delegation_client_id
        )["id"]

    master_token = admin_token()
    web = _client(admin_url, context, master_token, args.user_client_id)
    web_mappers_url = f"{admin_url}/clients/{web['id']}/protocol-mappers/models"
    mappers = _request(web_mappers_url, context, token=master_token)
    mapper_name = "identity-delegation-audience"
    if not any(mapper["name"] == mapper_name for mapper in mappers):
        _request(
            web_mappers_url,
            context,
            method="POST",
            token=master_token,
            body={
                "name": mapper_name,
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": args.delegation_client_id,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            },
        )

    for client_uuid_to_scope in (web["id"], client_uuid):
        for scope_id in scope_ids.values():
            master_token = admin_token()
            _request(
                f"{admin_url}/clients/{client_uuid_to_scope}/optional-client-scopes/{scope_id}",
                context,
                method="PUT",
                token=master_token,
            )

    probe = _load_probe()
    probe.run(
        argparse.Namespace(
            issuer=args.issuer,
            ca_file=args.ca_file,
            user_client_id=args.user_client_id,
            delegation_client_id=args.delegation_client_id,
            delegation_client_secret=client_secret,
            mcp_audience=args.mcp_audience,
            username=args.username,
            password=args.password,
            broad_scope=args.broad_scope,
            narrow_scope=args.narrow_scope,
        )
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--issuer", required=True)
    result.add_argument("--ca-file")
    result.add_argument("--admin-username", required=True)
    result.add_argument("--admin-password", required=True)
    result.add_argument("--user-client-id", default="genai-demo-web")
    result.add_argument("--delegation-client-id", default="identity-delegation")
    result.add_argument("--mcp-audience", default="mcp-gateway")
    result.add_argument("--username", required=True)
    result.add_argument("--password", required=True)
    result.add_argument("--broad-scope", default="mcp:catalog:read mcp:time:read")
    result.add_argument("--narrow-scope", default="mcp:time:read")
    return result


if __name__ == "__main__":
    run(parser().parse_args())
