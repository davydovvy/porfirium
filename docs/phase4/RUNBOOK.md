# Porfirium Phase 4 runbook

> Current runtime overlay (2026-08-23): the Phase 4 V1/V2 worker and `porfirium-agent-v1`
> queue are retired. Agent admission is open through the platform-owned `AgentRunWorkflow` on
> `porfirium-agent-runtime-v1`; the default release is `tool-assistant:1.1.0`. Historical Phase
> 4 behavior remains the regression baseline. Current static runtime verification is
> `./scripts/increment7/verify.sh`.

Phase 4 adds a bounded, policy-controlled tool loop to the durable Agent while preserving Direct mode and the replay-safe Phase 3 no-tool workflow.

Current transition note: Agentgateway is the sole MCP and model provider following accepted transition Increments 3–5. Accepted Increment 6 packages the Phase 4 tool assistant as immutable `tool-assistant:1.0.0`; the Phase 4 behavior and security boundaries below are unchanged.

## Start

Ensure the standalone Keycloak project is running, `portal.local` resolves to `127.0.0.1`, and the repository's uncommitted `.env` contains the generated local secrets and Yandex settings. Then run:

```bash
./scripts/phase4/start.sh
```

Startup builds the independently locked time and MTG catalog MCP services, starts Agentgateway and the existing platform services, applies migrations through `0007_generic_runtime`, and starts the portal API plus the sole generic Temporal worker. Agentgateway handles MCP and model traffic.

## Use and inspect

- Portal: <https://portal.local:8444>
- Temporal UI: <http://localhost:8080>
- Agentgateway: <http://localhost:8089>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Sign in as `alise` or `bob` with the local demo password `123456`. Select `Agent`, choose **Tool Assistant · 1.1.0**, create a conversation, and try either of these tasks:

- `Use the time tool to give the current time in Europe/Moscow.`
- `Search the MTG catalog for Cultivate in M11, retrieve its details, and report its dated snapshot price.`

The portal shows ordered tool-request, start, and completion steps followed by one complete assistant answer. Refreshing during a run reconnects to the persisted SSE stream without duplicating steps.

Agent workflow IDs are `porfirium-agent-<turn-id>`. New runs use `AgentRunWorkflow` on `porfirium-agent-runtime-v1`; retired V1/V2 definitions are not registered by the production worker. At acceptance, each Agent turn stores an immutable snapshot containing the selected version identity and digest, resolved model target, instructions, reviewed tool definitions and grants, and execution limits. Search by workflow ID in Temporal UI. The turn's 32-character correlation ID is its W3C trace ID; standard trace context is propagated through Agentgateway for model and MCP execution, so model generations, tool execution, and application observations appear under one Langfuse trace. Tool audit rows remain owner-scoped and are not exposed through a cross-user inspection endpoint.

## Verify

```bash
./scripts/phase4/verify.sh
```

Verification runs both MCP unit suites, backend lint/tests, frontend lint/test/build, Compose validation, the secret-pattern scan, and the Increment 7 static runtime gate. The paid Phase 4 smoke scripts remain available as historical regression tools, but are not invoked automatically by `phase4/verify.sh`. Run them deliberately when credentials, provider cost, worker restart, and test-user state are in scope.

The preserved behavior regressions can be repeated separately. The Phase 3 smoke submits a no-tool task through the current Agent route and restarts the worker; it does not create a new V1 workflow:

```bash
./scripts/phase3/smoke.sh
./scripts/phase2/smoke.sh
```

## Status, logs, recovery, and stop

```bash
./scripts/phase4/status.sh
docker compose logs --tail=100 agent-worker portal-api agentgateway demo-time-mcp demo-mtg-catalog-mcp
./scripts/phase4/stop.sh
```

If a tool service is unhealthy, inspect its logs and restart that exact service. If Agentgateway is unhealthy, inspect `agentgateway` and restart only that service; the compatibility gate verifies target and gateway recovery. If `agent-worker` is unavailable, restart it with `docker compose restart agent-worker`; accepted workflows remain durable and resume from Temporal history.

If the portal appears to wait for a worker while `agent-worker` is running, inspect the worker
logs before changing queues or starting replacement work:

```bash
docker compose logs --tail=200 agent-worker
```

`Failed decoding arguments` indicates an activity contract/payload-converter mismatch, not a
missing poller. Fix and redeploy the worker first. If the execution has already exhausted its
retries, confirm that the application turn is still non-terminal and restart the failed
execution with the same workflow ID and original immutable `run_snapshot_id`. Never create a
new snapshot or rewrite the accepted turn to recover it.

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, Agentgateway, and Langfuse state is intended. Increment 5 did not delete the old unreferenced Bifrost volume.

## Security and phase boundary

Only the reviewed read-only time and bundled catalog tools are available to `tool_assistant_v1`. The application validates exact tool identity, schema, size limits, and policy on every proposed call before execution. Agentgateway CEL authorization is defense in depth; application policy remains authoritative, and approved function definitions are supplied explicitly. Browser bearer tokens and browser-controlled user identifiers are not forwarded to Agentgateway or MCP services. Catalog prices are dated Scryfall snapshots with source metadata, not live quotes; see [the data provenance notes](../../services/mtg-catalog-mcp/data/README.md).

Side-effecting tools, approval UI, live prices, arbitrary retrieval, delegated user credentials, and broader dependency-failure hardening remain deferred.
