# Porfirium Phase 4 runbook

Phase 4 adds a bounded, policy-controlled tool loop to the durable Agent while preserving Direct mode and the replay-safe Phase 3 no-tool workflow.

## Start

Ensure the standalone Keycloak project is running, `portal.local` resolves to `127.0.0.1`, and the repository's uncommitted `.env` contains the generated local secrets and Yandex settings. Then run:

```bash
./scripts/phase4/start.sh
```

Startup builds the independently locked time and MTG catalog MCP services, starts the existing platform services, applies migration `0004_phase4_tool_audit`, verifies Bifrost's persisted deny-by-default MCP setting, and starts the portal API and both Temporal workflow versions.

## Use and inspect

- Portal: <https://portal.local:8444>
- Temporal UI: <http://localhost:8080>
- Bifrost: <http://localhost:8088>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Sign in as `alise` or `bob` with the local demo password `123456`. Select `Agent`, create a conversation, and try either of these tasks:

- `Use the time tool to give the current time in Europe/Moscow.`
- `Search the MTG catalog for Cultivate in M11, retrieve its details, and report its static demo price.`

The portal shows ordered tool-request, start, and completion steps followed by one complete assistant answer. Refreshing during a run reconnects to the persisted SSE stream without duplicating steps.

Tool-capable workflow IDs are `porfirium-tool-agent-<turn-id>`. Search for the workflow in Temporal UI. The turn correlation ID is its W3C trace ID and locates the model and tool observations in Langfuse. Tool audit rows remain owner-scoped and are not exposed through a cross-user inspection endpoint.

## Verify

```bash
./scripts/phase4/verify.sh
```

Verification runs both MCP unit suites, backend lint/tests, frontend lint/test/build, Compose validation, the secret-pattern scan, Bifrost policy validation, and the live Phase 4 smoke. The live smoke exercises a time call across an `agent-worker` restart, a three-tool MTG request, prompt-injection denial, audit/event idempotency, trace correlation, and two-user isolation. It makes paid Yandex requests.

The preserved regressions can be repeated separately:

```bash
./scripts/phase3/smoke.sh
./scripts/phase2/smoke.sh
```

## Status, logs, recovery, and stop

```bash
./scripts/phase4/status.sh
docker compose logs --tail=100 agent-worker portal-api bifrost demo-time-mcp demo-mtg-catalog-mcp
./scripts/phase4/stop.sh
```

If a tool service is unhealthy, inspect its logs and restart that exact service. If `agent-worker` is unavailable, restart it with `docker compose restart agent-worker`; accepted workflows remain durable and resume from Temporal history. If Bifrost policy validation fails, rerun `./scripts/phase3/bifrost-policy.sh` before accepting Agent traffic.

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, Bifrost, and Langfuse state is intended.

## Security and phase boundary

Only the reviewed read-only time and bundled catalog tools are available to `tool_assistant_v1`. The application validates exact tool identity, schema, size limits, and policy on every proposed call before execution. Bifrost automatic tool injection/execution remains disabled. Browser bearer tokens and browser-controlled user identifiers are not forwarded to Bifrost or MCP services.

Side-effecting tools, approval UI, live prices, arbitrary retrieval, delegated user credentials, and broader dependency-failure hardening remain deferred.
