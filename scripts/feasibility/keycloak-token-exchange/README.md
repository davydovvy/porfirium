# Keycloak delegated token-exchange gate

Status: **accepted on Keycloak 26.2.5**

This gate proves that the selected Keycloak realm can issue an MCP-audience token with narrowed
scopes, repeat the exchange for renewal without returning a refresh token to an agent attempt, and
reject a new exchange after the user's session is logged out.

The realm must provide:

- a public test-user client with direct access grants (test-only bootstrap);
- a confidential Identity Delegation client allowed to exchange the user's access token;
- an MCP Gateway audience and client scopes `mcp:catalog:read` and `mcp:time:read`;
- exchange policy restricting the delegation client to that audience and requested scopes.

Run the live gate without putting credentials in the repository:

```bash
export KEYCLOAK_ISSUER=https://keycloak.example/realms/porfirium
export KEYCLOAK_CA_FILE=/path/to/ca.pem
export KEYCLOAK_USER_CLIENT_ID=porfirium-feasibility-user
export KEYCLOAK_DELEGATION_CLIENT_ID=identity-delegation
export KEYCLOAK_DELEGATION_CLIENT_SECRET=...
export KEYCLOAK_MCP_AUDIENCE=mcp-gateway
export KEYCLOAK_TEST_USERNAME=...
export KEYCLOAK_TEST_PASSWORD=...
./scripts/feasibility/keycloak-token-exchange/verify.sh
```

Acceptance requires all three `PASS` lines. A configured live realm is deliberately mandatory;
syntax checks or a mocked OAuth server do not establish Keycloak feasibility. The probe decodes
claims only to assert the response from the TLS-authenticated token endpoint; production services
must still verify signatures, issuer, audience, expiry, and run context.

For a disposable local realm, `configure_and_probe.py` creates the clients and scopes through the
admin API, generates the confidential client secret only in memory, and runs the same assertions:

```bash
python3 scripts/feasibility/keycloak-token-exchange/configure_and_probe.py \
  --issuer http://127.0.0.1:8180/realms/GenAI-platform \
  --admin-username "$KEYCLOAK_ADMIN_USERNAME" \
  --admin-password "$KEYCLOAK_ADMIN_PASSWORD" \
  --username "$KEYCLOAK_TEST_USERNAME" \
  --password "$KEYCLOAK_TEST_PASSWORD"
```

## Accepted observation

On 2026-09-05 the gate passed on Keycloak 26.2.5. The test exchanged a Portal Web user token through
a confidential Identity Delegation client, produced a token restricted to the `mcp-gateway`
audience, narrowed two requested MCP scopes to one, renewed without returning a refresh token, and
rejected exchange of the original subject token after logout.

Decision: use Standard Token Exchange V2 with Keycloak 26.2.5 or newer in the target stack. Keep
refresh-token issuance disabled for the Identity Delegation client. Runtime policy must still
intersect user scopes with the pinned release and platform grants; Keycloak token exchange alone
does not establish run authorization.
