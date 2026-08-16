# Keycloak Phase 0 design confirmation

> Historical Phase 0 decision record. The planned `GenAI-platform` realm described here is now implemented in the standalone Keycloak project.

Phase 0 does not mutate the standalone Keycloak project. It confirms the Phase 1 target:

- standalone project: `/home/dvy/Projects/KeyCloak`;
- new realm: `GenAI-platform`;
- canonical issuer: `https://keycloak.local:8443/realms/GenAI-platform`;
- portal client: `genai-demo-web`, public, Authorization Code + PKCE;
- API audience/client: `genai-demo-api`;
- roles: `genai-user`, reserved `genai-tool-approver`, and `genai-admin`;
- at least two demo users for visible isolation testing;
- existing local CA reused for `keycloak.local` trust.

The existing `mcp-gateway` realm remains untouched. Realm creation, clients, roles, and users are Phase 1 implementation work.

## Phase 0 finding

The running standalone Keycloak instance exposes the canonical HTTPS `master` realm successfully. Its Compose file starts Keycloak with `--import-realm`, but does not currently mount `keycloak/mcp-gateway-realm.json` into `/opt/keycloak/data/import`. On a fresh volume, the documented `mcp-gateway` realm is therefore absent. Phase 1 must add a mount for the new `GenAI-platform` realm export (and may separately repair the legacy import if desired) before relying on realm bootstrap.
