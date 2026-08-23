# Increment 6.5 legacy runtime retirement results

Date: 2026-08-23  
Status: Implemented; maintenance interval superseded by Increment 7

> Historical-state note: this document records the bounded Increment 6.5 maintenance state.
> Increment 7 has since reopened Agent admission through the generic runtime; the retirement of
> the legacy queue and V1/V2 production registrations remains in effect.

## Delivered

- Agent turn admission is fail-closed in explicit `maintenance` mode and returns HTTP `503`
  with stable code `agent_runtime_maintenance` before creating a turn, message, snapshot, event,
  or workflow.
- Capabilities, readiness, configuration, and the portal expose the maintenance state. Existing
  Agent conversations remain readable, while their composer is disabled. Direct mode remains
  enabled.
- The `agent-worker` Compose service, `TEMPORAL_TASK_QUEUE`, `porfirium-agent-v1` production
  configuration, workflow start path, and V1/V2 production workflow/activity modules were
  removed.
- Phase start/status/stop scripts no longer reference the retired worker. Current verification
  uses the Increment 6.5 maintenance and retirement gate instead of the historical paid Agent
  smoke.
- `scripts/increment6_5/inventory.sh` reconciles active application Agent turns, open V1/V2
  Temporal executions, and recently active legacy queue pollers.
- `scripts/increment6_5/smoke.py` authenticates through Keycloak, verifies advertised
  maintenance, attempts an Agent turn, and proves rejection caused no partial persistence.

The immutable `tool-assistant:1.0.0` publication, completed Temporal histories, conversations,
messages, snapshots, events, tool audits, and traces were not deleted or mutated.

## Live retirement evidence

Before source/runtime removal, read-only database and Temporal queries reported zero active
Agent turns and zero open V1/V2 executions. After rebuilding the API and portal with orphan
removal, the legacy worker container was stopped and removed.

Two post-removal inventory runs reported:

```text
PASS: zero active Agent turns, open legacy executions, and legacy workflow pollers
```

The live maintenance smoke reported:

```text
PASS: Agent maintenance is visible and rejected before turn persistence
PASS: Increment 6.5 legacy runtime retirement gate
```

Compose status contains no Agent worker. The API and portal are healthy, and the running stack
contains the retained infrastructure services only.

During `docker compose up --remove-orphans`, Compose also removed already-retired orphan
containers for Bifrost and the Agentgateway spike. Their persistent data was not deleted, and
neither service was part of the current Compose model.

## Automated evidence

- backend Ruff passes;
- all 30 backend tests pass, including fail-closed maintenance/configuration tests;
- frontend lint and component test pass;
- frontend production build passes;
- Compose renders successfully;
- `git diff --check` passes.

The complete migration regression gate also passes against the retired topology. It includes
the Agentgateway readiness, MCP inventory/execution/denial, W3C trace, Langfuse ingestion,
Yandex Responses/streaming/schema/tool-continuation, dependency-restart recovery, and Phase 2
Direct-mode persistence, idempotency, SSE replay, isolation, and trace checks, followed by the
Increment 6.5 live gate.

## Handoff outcome

Increment 7 started from this zero-legacy maintenance state and deployed the generic worker,
schema-v2 release, transactional conversation upgrade, and reopened admission. It did not
restore the retired queue or production workflow registrations.
