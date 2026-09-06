# Identity Delegation

Identity Delegation stores durable, opaque delegation grants and mints short-lived MCP Gateway
tokens. Grants are bound to a user, conversation, release, maximum scopes, expiry, and revocation
state. Exchange and renewal additionally require an active signed run assertion matching the exact
grant, release, run, attempt, and lease epoch. Refresh tokens are never returned or stored here.

Apply the service-owned migration before starting the API:

```bash
uv run python -m identity_delegation.migrate
uv run uvicorn identity_delegation.main:app --host 0.0.0.0 --port 8105
```

Required configuration is `DATABASE_URL` and `DELEGATION_SIGNING_SECRET`; readiness also requires
the NATS variables. Supply the signing secret through deployment secret management and rotate it as
a coordinated issuer/gateway change. `X-User-ID` represents identity already verified at the BFF
boundary and must not be forwarded from an untrusted browser request.

The gateway policy endpoints enforce model grants using the run authorization. MCP authorization
requires both the pinned run tool grant and the matching `tool:<name>` delegated user scope. Run,
attempt, and lease claims must match across credentials, and cancelled runs reject new model and
tool work. Apply `identity_delegation.redaction.redact` before emitting untrusted data to logs,
events, traces, metrics attributes, or rendered errors.

Run the focused suite from the repository root with `./scripts/target-phase7/verify.sh`.
