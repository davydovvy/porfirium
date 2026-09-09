# Portal cutover plan

Phase 13 reuses the existing React portal with the target platform. Legacy agents, conversations,
messages, runs, checkpoints, application data, and Temporal history will not be migrated or backed
up. Users start with an empty target conversation list and only the releases already published in
the target Registry. Keycloak remains the identity provider.

The public portal remains `https://portal.local:8444` and routes exclusively to target
`portal-bff:8100`. Shared Keycloak, Agentgateway, MCP, and observability services remain in service.

## Current state

- The React application already uses the target `/api/v1` endpoints and passed Phase 12 component
  and live acceptance.
- Its Caddy image requires the deployment-time Portal BFF upstream; there is no legacy fallback.
- The target Compose topology runs the portal against Portal BFF and publishes the public origin on
  `127.0.0.1:8444`. The `18444` rehearsal origin remains available through an explicit port
  override.
- The local Keycloak web client accepts both the rehearsal and public portal origins for login and
  post-logout redirects.
- The legacy Portal, Portal API, worker, Temporal, application PostgreSQL, their code, and obsolete
  local volumes have been removed.
- Signed `model-only` 1.0.1 and `planning-assistant` 1.1.1 releases are published and passed the
  complete Phase 12 live matrix.

## Acceptance evidence

- The focused portal gate passes against the public origin.
- The complete Phase 12 baseline passes, including recovery and the live two-agent matrix.
- Public browser login, logout, identity, conversations, streaming, cancellation, and agent
  selection were confirmed after cutover.
- Removing the legacy runtime did not affect target portal readiness.

## Rollback

Rollback restores the last accepted target portal image and target Caddy configuration. It does
not restore the legacy platform or its data. Keep the previous accepted target portal image digest
and Compose configuration until the new portal has passed the public-origin checks. Target service
data remains authoritative throughout rollback.

## Exit gate

Phase 13 is complete. The public portal routes only to Portal BFF, its acceptance gates pass, and
the legacy runtime has been removed without affecting the target platform.

## Separate follow-up

Preserve sanitized attempt exit status before container cleanup to improve future diagnostics.
This does not block the portal cutover.
