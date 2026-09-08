# Portal cutover plan

Phase 13 reuses the existing React portal with the target platform. Legacy agents, conversations,
messages, runs, checkpoints, application data, and Temporal history will not be migrated or backed
up. Users start with an empty target conversation list and only the releases already published in
the target Registry. Keycloak remains the identity provider.

The public portal remains `https://portal.local:8444`. The cutover replaces its backend route from
legacy `portal-api:8000` to target `portal-bff:8100`. Shared Keycloak, Agentgateway, MCP, and
observability services remain in service.

## Current state

- The React application already uses the target `/api/v1` endpoints and passed Phase 12 component
  and live acceptance.
- Its Caddy image accepts a deployment-time API upstream and retains `portal-api:8000` as the
  legacy Compose default.
- The target Compose topology runs the portal against Portal BFF and publishes its rehearsal origin
  on `127.0.0.1:18444`.
- The local Keycloak web client accepts both the rehearsal and public portal origins for login and
  post-logout redirects.
- The legacy Portal, Portal API, worker, Temporal, and application PostgreSQL services and the
  legacy application volume are absent from this workstation. Nothing from them is required for
  this cutover.
- Signed `model-only` 1.0.1 and `planning-assistant` 1.1.1 releases are published and passed the
  complete Phase 12 live matrix.

## Implementation sequence

1. Make the portal image's API upstream configurable at deployment time. Keep the legacy Compose
   default as `portal-api:8000`, and configure the target deployment as `portal-bff:8100`. Keep API
   requests same-origin so browser tokens remain at the Portal BFF boundary.
2. Add the existing portal image to the target Compose topology on a rehearsal port such as
   `18444`. Give it only the target network connection needed to reach Portal BFF. Preserve the
   existing TLS, security headers, SPA fallback, and Keycloak browser client settings.
3. Add a target portal verification script. It must validate the rendered Compose configuration,
   Caddy routing, frontend lint/tests/build, Portal BFF readiness through the portal origin, and the
   absence of any dependency on Portal API, Temporal, or the legacy application database.
4. Run browser-level acceptance through the rehearsal portal origin. Verify login/logout, identity,
   empty conversation state for a fresh user, agent selection, message streaming, cancellation,
   delegated time-tool output, authorization boundaries, and agent publication controls.
5. Run the complete Phase 12 gate again against the same target services used by the portal. The
   two agents must still reach durable Runner completion with the expected tool records.
6. Switch the public portal by stopping the old portal container and starting the verified target
   portal on `127.0.0.1:8444`. Do not start Portal API, agent-worker, Temporal, Temporal UI, or the
   legacy application database.
7. Repeat portal health, authentication, fresh conversation, streaming, cancellation, and both
   agent checks through `https://portal.local:8444`.
8. Remove legacy service definitions and code only after the public portal checks pass. This
   cleanup may delete legacy application and Temporal storage because the user has explicitly
   waived migration, backup, and history retention.

## Rollback

Rollback restores the last accepted target portal image and target Caddy configuration. It does
not restore the legacy platform or its data. Keep the previous accepted target portal image digest
and Compose configuration until the new portal has passed the public-origin checks. Target service
data remains authoritative throughout rollback.

## Exit gate

Phase 13 is complete when `https://portal.local:8444` serves the existing React portal through
Portal BFF, all portal and Phase 12 checks pass, no portal route or dependency refers to Portal API
or Temporal, and the legacy runtime can remain stopped or be removed without affecting the target
platform.

## Separate follow-up

Preserve sanitized attempt exit status before container cleanup to improve future diagnostics.
This does not block the portal cutover.
