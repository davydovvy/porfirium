# Porfirium Phase 4 runbook

Phase 4 adds a bounded, policy-controlled tool loop to the durable Agent while preserving Direct mode and the replay-safe Phase 3 no-tool workflow.

Current transition note: Agentgateway is now the default MCP and model provider following accepted transition Increments 3 and 4. Bifrost remains the configuration-only rollback until retirement. The Phase 4 behavior and security boundaries below are unchanged.

## Start

Ensure the standalone Keycloak project is running, `portal.local` resolves to `127.0.0.1`, and the repository's uncommitted `.env` contains the generated local secrets and Yandex settings. Then run:

```bash
./scripts/phase4/start.sh
```

Startup builds the independently locked time and MTG catalog MCP services, starts Agentgateway and the existing platform services, applies migration `0004_phase4_tool_audit`, verifies Bifrost's persisted deny-by-default MCP setting for rollback safety, and starts the portal API and both Temporal workflow versions. Agentgateway handles current MCP and model traffic; Bifrost remains running only as the immediate rollback until Increment 5.

## Use and inspect

- Portal: <https://portal.local:8444>
- Temporal UI: <http://localhost:8080>
- Bifrost: <http://localhost:8088>
- Agentgateway: <http://localhost:8089>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Sign in as `alise` or `bob` with the local demo password `123456`. Select `Agent`, create a conversation, and try either of these tasks:

- `Use the time tool to give the current time in Europe/Moscow.`
- `Search the MTG catalog for Cultivate in M11, retrieve its details, and report its dated snapshot price.`

The portal shows ordered tool-request, start, and completion steps followed by one complete assistant answer. Refreshing during a run reconnects to the persisted SSE stream without duplicating steps.

Agent workflow IDs are `porfirium-agent-<turn-id>`. New Phase 4 runs use the `PorfiriumToolAgentWorkflowV2` definition; V1 remains registered for replay compatibility with existing histories. Search by workflow ID in Temporal UI. The turn's 32-character correlation ID is its W3C trace ID; standard trace context is propagated through Agentgateway for model and MCP execution, so model generations, tool execution, and application observations appear under one Langfuse trace. Tool audit rows remain owner-scoped and are not exposed through a cross-user inspection endpoint.

## Verify

```bash
./scripts/phase4/verify.sh
```

Verification runs both MCP unit suites, backend lint/tests, frontend lint/test/build, Compose validation, the secret-pattern scan, Bifrost policy validation, and the live Phase 4 smoke. The live smoke exercises a time call across an `agent-worker` restart, a three-tool MTG request, prompt-injection denial, audit/event idempotency, trace correlation, and two-user isolation. Under the expected tool-selection path it makes seven paid Yandex model requests: two for time selection/synthesis, four for the three MTG calls plus synthesis, and one denial response. Provider behavior can alter the number if a request is retried.

The preserved behavior regressions can be repeated separately. The Phase 3 smoke submits a no-tool task through the current Agent route and restarts the worker; it does not create a new V1 workflow:

```bash
./scripts/phase3/smoke.sh
./scripts/phase2/smoke.sh
```

## Status, logs, recovery, and stop

```bash
./scripts/phase4/status.sh
docker compose logs --tail=100 agent-worker portal-api bifrost agentgateway-spike demo-time-mcp demo-mtg-catalog-mcp
./scripts/phase4/stop.sh
```

If a tool service is unhealthy, inspect its logs and restart that exact service. If Agentgateway is unhealthy, inspect `agentgateway-spike` and restart only that service; the spike gate verifies target and gateway recovery. If `agent-worker` is unavailable, restart it with `docker compose restart agent-worker`; accepted workflows remain durable and resume from Temporal history. If Bifrost policy validation fails, rerun `./scripts/phase3/bifrost-policy.sh` before relying on MCP rollback. To roll back one role independently, recreate the application with `MODEL_GATEWAY_PROVIDER=bifrost` or `TOOL_GATEWAY_PROVIDER=bifrost`; set both for complete gateway rollback.

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, Bifrost, Agentgateway, and Langfuse state is intended.

## Security and phase boundary

Only the reviewed read-only time and bundled catalog tools are available to `tool_assistant_v1`. The application validates exact tool identity, schema, size limits, and policy on every proposed call before execution. Agentgateway CEL authorization is defense in depth; application policy remains authoritative. Approved function definitions are supplied explicitly to Agentgateway; Bifrost automatic tool injection/execution remains disabled for rollback safety. Browser bearer tokens and browser-controlled user identifiers are not forwarded to Bifrost, Agentgateway, or MCP services. Catalog prices are dated Scryfall snapshots with source metadata, not live quotes; see [the data provenance notes](../../services/mtg-catalog-mcp/data/README.md).

Side-effecting tools, approval UI, live prices, arbitrary retrieval, delegated user credentials, and broader dependency-failure hardening remain deferred.
