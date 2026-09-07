from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:8180"
REALM = "GenAI-platform"
CLIENT_ID = "porfirium-target-dev"
CLIENT_SECRET = "dev-target-oidc-client-secret"
ROLES = (
    "genai-agent-publisher",
    "genai-agent-registry-admin",
    "genai-agent-run-resolver",
)


def request(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    body: object | None = None,
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
    call = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(call, timeout=15) as response:
        content = response.read()
        return json.loads(content) if content else None


def one(items: list[dict[str, Any]], description: str) -> dict[str, Any]:
    if len(items) != 1:
        raise RuntimeError(f"expected one {description}, found {len(items)}")
    return items[0]


def main() -> None:
    admin_token = request(
        "/realms/master/protocol/openid-connect/token",
        method="POST",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "changeme",
        },
    )["access_token"]
    admin = f"/admin/realms/{REALM}"

    existing_roles = {item["name"] for item in request(f"{admin}/roles", token=admin_token)}
    for role in ROLES:
        if role not in existing_roles:
            request(
                f"{admin}/roles",
                token=admin_token,
                method="POST",
                body={"name": role, "description": "Porfirium target development role"},
            )

    demo_user = one(
        request(
            f"{admin}/users?{urllib.parse.urlencode({'username': 'Alise', 'exact': 'true'})}",
            token=admin_token,
        ),
        "Alise demo user",
    )

    registry_clients = request(
        f"{admin}/clients?{urllib.parse.urlencode({'clientId': 'agent-registry'})}",
        token=admin_token,
    )
    if not registry_clients:
        request(
            f"{admin}/clients",
            token=admin_token,
            method="POST",
            body={
                "clientId": "agent-registry",
                "name": "Porfirium Agent Registry audience",
                "enabled": True,
                "bearerOnly": True,
                "protocol": "openid-connect",
            },
        )

    clients = request(
        f"{admin}/clients?{urllib.parse.urlencode({'clientId': CLIENT_ID})}", token=admin_token
    )
    representation = {
        "clientId": CLIENT_ID,
        "name": "Porfirium target development services",
        "enabled": True,
        "publicClient": False,
        "bearerOnly": False,
        "clientAuthenticatorType": "client-secret",
        "secret": CLIENT_SECRET,
        "protocol": "openid-connect",
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True,
        "attributes": {
            "standard.token.exchange.enabled": "true",
            "standard.token.exchange.enableRefreshRequestedTokenType": "false",
        },
        "protocolMappers": [
            {
                "name": "agent-registry-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": "agent-registry",
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            },
            {
                "name": "demo-resolver-user-context",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-hardcoded-claim-mapper",
                "config": {
                    "claim.name": "porfirium_user_id",
                    "claim.value": demo_user["id"],
                    "jsonType.label": "String",
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            },
        ],
    }
    if clients:
        client_uuid = one(clients, CLIENT_ID)["id"]
        representation["id"] = client_uuid
        request(
            f"{admin}/clients/{client_uuid}",
            token=admin_token,
            method="PUT",
            body=representation,
        )
    else:
        request(f"{admin}/clients", token=admin_token, method="POST", body=representation)
        clients = request(
            f"{admin}/clients?{urllib.parse.urlencode({'clientId': CLIENT_ID})}",
            token=admin_token,
        )
        client_uuid = one(clients, CLIENT_ID)["id"]

    service_user = request(
        f"{admin}/clients/{client_uuid}/service-account-user", token=admin_token
    )
    realm_roles = [request(f"{admin}/roles/{role}", token=admin_token) for role in ROLES]
    request(
        f"{admin}/users/{service_user['id']}/role-mappings/realm",
        token=admin_token,
        method="POST",
        body=realm_roles,
    )

    web = one(
        request(
            f"{admin}/clients?{urllib.parse.urlencode({'clientId': 'genai-demo-web'})}",
            token=admin_token,
        ),
        "genai-demo-web",
    )
    mapper_path = f"{admin}/clients/{web['id']}/protocol-mappers/models"
    mappers = request(mapper_path, token=admin_token)
    if not any(item["name"] == "porfirium-target-audience" for item in mappers):
        request(
            mapper_path,
            token=admin_token,
            method="POST",
            body={
                "name": "porfirium-target-audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {
                    "included.client.audience": CLIENT_ID,
                    "access.token.claim": "true",
                    "id.token.claim": "false",
                },
            },
        )

    token = request(
        f"/realms/{REALM}/protocol/openid-connect/token",
        method="POST",
        form={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )["access_token"]
    introspection = request(
        f"/realms/{REALM}/protocol/openid-connect/token/introspect",
        method="POST",
        form={"token": token, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
    )
    if introspection.get("active") is not True or "agent-registry" not in introspection.get(
        "aud", []
    ):
        raise RuntimeError("target service token failed introspection")
    missing = set(ROLES) - set(introspection.get("realm_access", {}).get("roles", []))
    if missing:
        raise RuntimeError(f"target service token is missing roles: {sorted(missing)}")
    if introspection.get("porfirium_user_id") != demo_user["id"]:
        raise RuntimeError("target service token is missing the demo user context")
    user_token = request(
        f"/realms/{REALM}/protocol/openid-connect/token",
        method="POST",
        form={
            "grant_type": "password",
            "client_id": "genai-demo-web",
            "username": "Alise",
            "password": "123456",
        },
    )["access_token"]
    exchanged = request(
        f"/realms/{REALM}/protocol/openid-connect/token",
        method="POST",
        form={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": "agent-registry",
        },
    )["access_token"]
    exchanged_claims = request(
        f"/realms/{REALM}/protocol/openid-connect/token/introspect",
        method="POST",
        form={
            "token": exchanged,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    audiences = exchanged_claims.get("aud", [])
    if exchanged_claims.get("active") is not True or "agent-registry" not in audiences:
        raise RuntimeError("browser token exchange failed Registry audience validation")
    print("PASS: target Keycloak client, audience, service account, and roles")


if __name__ == "__main__":
    main()
