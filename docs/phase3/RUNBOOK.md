# Porfirium Phase 3 runbook

> Current runtime overlay (2026-08-23): the Phase 3/4 legacy Agent worker and queue are retired.
> Agent admission is open through `AgentRunWorkflow` on `porfirium-agent-runtime-v1`. The Phase 3
> no-tool workflow descriptions remain historical regression context; worker restart commands
> now operate on the generic worker.

> Current transition note (2026-08-22): Agentgateway is the sole model and MCP provider. The Phase 3 results document preserves the retired Bifrost-era acceptance evidence.

Phase 3 adds a Temporal-backed, no-tool Agent mode while preserving Direct LLM chat. Keycloak remains a separately managed prerequisite.

## Start

Ensure Keycloak is running, `portal.local` resolves to `127.0.0.1`, and the repository's uncommitted `.env` contains the generated local secrets and Yandex settings. Then run:

```bash
./scripts/phase3/start.sh
```

The first start downloads the pinned Temporal server and UI images and may take several minutes. Startup applies the complete migration chain through `0007_generic_runtime` automatically and starts the generic worker.

Agentgateway requests receive only the reviewed tool definitions captured in the immutable run snapshot. The original replay-safe Phase 3 workflow is retained only as historical evidence and is not registered in production.

## Use and inspect

- Portal: <https://portal.local:8444>
- Temporal UI: <http://localhost:8080>
- Agentgateway: <http://localhost:8089>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Sign in as `alise` or `bob` with the local demo password `123456`. The Direct/Agent selector filters the sidebar to conversations in that mode and controls the mode used by the new-conversation button. Switching modes opens the most recent matching conversation, or shows the empty state when none exists.

Select `Agent`, create a conversation, and submit a task. The portal renders durable status events and then one complete response. Refreshing the browser while a run is active reconnects to its persisted SSE event stream. Long message histories scroll within the workspace; the conversation list scrolls independently while the signed-in user and sign-out button remain pinned at the bottom of the sidebar.

The workflow ID is `porfirium-agent-<turn-id>`. Search for it in Temporal UI. The turn's correlation ID is also its 32-character W3C trace ID and can be used to locate the selected gateway's generation path in Langfuse.

## Verify

```bash
./scripts/phase3/verify.sh
```

The preserved live smoke creates an Agent conversation through the current generic route, waits for its planning event, restarts `agent-worker`, and requires the same Temporal workflow to finish and persist its response. It makes paid Yandex requests and is not part of the default static Increment 7 gate.

To exercise recovery manually:

```bash
docker compose restart agent-worker
./scripts/phase3/status.sh
```

Temporal retains workflow history in the application PostgreSQL instance and dispatches unfinished work when the worker returns. Ordinary stack stop/start does not delete that state.

## Status, logs, and stop

```bash
./scripts/phase3/status.sh
docker compose logs --tail=100 temporal agent-worker portal-api
./scripts/phase3/stop.sh
```

If Temporal is unhealthy, inspect `docker compose logs temporal`. If the worker is unavailable, restart it with `docker compose restart agent-worker`; accepted workflows remain queued. If the API is unhealthy after an upgrade, inspect `docker compose logs portal-api` for migration errors.

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, Agentgateway, and Langfuse state is intended.

## Phase boundary

This historical runbook originally exercised Agent workflow V1, which deliberately had no tools and performed one model activity. The current generic Agent path retains the user-visible durability contract and adds snapshot-backed time/catalog tools, validation, read-only execution policy, and tool-status events. V1 is no longer registered by the production worker; completed histories remain historical records.
