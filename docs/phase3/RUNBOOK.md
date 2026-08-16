# Porfirium Phase 3 runbook

Phase 3 adds a Temporal-backed, no-tool Agent mode while preserving Direct LLM chat. Keycloak remains a separately managed prerequisite.

## Start

Ensure Keycloak is running, `portal.local` resolves to `127.0.0.1`, and the repository's uncommitted `.env` contains the generated local secrets and Yandex settings. Then run:

```bash
./scripts/phase3/start.sh
```

The first start downloads the pinned Temporal server and UI images and may take several minutes. Startup applies database migration `0003_phase3` automatically.

Startup also verifies Bifrost's persisted `mcp_disable_auto_tool_inject` setting and repairs it to `true` when necessary. This prevents the Phase 0 diagnostic tools from leaking into Phase 3 Agent requests before the Phase 4 policy/execution loop exists.

## Use and inspect

- Portal: <https://portal.local:8444>
- Temporal UI: <http://localhost:8080>
- Bifrost: <http://localhost:8088>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Sign in as `alise` or `bob` with the local demo password `123456`. The Direct/Agent selector filters the sidebar to conversations in that mode and controls the mode used by the new-conversation button. Switching modes opens the most recent matching conversation, or shows the empty state when none exists.

Select `Agent`, create a conversation, and submit a task. The portal renders durable status events and then one complete response. Refreshing the browser while a run is active reconnects to its persisted SSE event stream. Long message histories scroll within the workspace; the conversation list scrolls independently while the signed-in user and sign-out button remain pinned at the bottom of the sidebar.

The workflow ID is `porfirium-agent-<turn-id>`. Search for it in Temporal UI. The turn's correlation ID is also its 32-character W3C trace ID and can be used to locate the Bifrost generation path in Langfuse.

## Verify

```bash
./scripts/phase3/verify.sh
```

The live smoke test creates an Agent conversation, waits for its planning event, restarts `agent-worker`, and requires the same Temporal workflow to finish and persist its response. It makes one paid Yandex request.

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

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, Bifrost, and Langfuse state is intended.

## Phase boundary

Agent v1 deliberately has no tools and performs one model activity. If asked to use tools, it must explain that they are unavailable rather than attempting a call. MCP time/catalog servers, tool validation, read-only execution policy, and tool status events begin in Phase 4.
