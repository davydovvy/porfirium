# Porfirium Phase 1 implementation results

Date: 2026-08-16  
Status: Implemented and accepted by the user on 2026-08-16.

## Delivered

- React/TypeScript portal shell served through local HTTPS by Caddy;
- Authorization Code + PKCE Keycloak client and dedicated API audience;
- local JWT signature, issuer, audience, expiry, and `genai-user` role validation;
- Alise and Bob demo identities with distinct internal pseudonymous user records;
- FastAPI liveness, readiness, configuration, identity, and protected empty-conversation endpoints;
- separate PostgreSQL database and Alembic identity/conversation migration;
- pinned Python and JavaScript lockfiles, lint, unit tests, secret-pattern scan, and CI workflow;
- start, stop, status, smoke, and verification scripts.

## Verified evidence

The live smoke test reported:

```text
PASS: authenticated alise with protected identity endpoint
PASS: authenticated bob with protected identity endpoint
PASS: unauthenticated access rejected and demo identities are isolated
```

Automated API checks: 6 passed. Frontend checks: lint passed, 1 component test passed, production build passed. The production npm dependency audit reported zero vulnerabilities.

## Known limitations

- The Caddy local root CA requires a one-time browser/OS trust action.
- Direct Access Grants are enabled on the local public client only to make the deterministic two-user smoke test possible; the browser uses Authorization Code + PKCE.
- The application schema contains the Phase 1 conversation ownership skeleton, but conversation creation and messages intentionally begin in Phase 2.
- GitHub Action references are version-tag pinned rather than commit-SHA pinned and should be tightened during hardening.

## Accepted dependency exception

MinIO's upstream AGPL-3.0 license is accepted for this local demo to preserve the supported self-hosted Langfuse topology. This decision must be revisited before production redistribution or a materially different deployment model.
