# Phase 2 runbook

> Current transition note (2026-08-22): Agentgateway is the sole model and MCP provider. The Phase 2 results document preserves the retired Bifrost-era acceptance evidence.

Phase 2 adds persistent Direct LLM conversations, Yandex Responses API streaming through the selected model gateway, replayable application SSE events, cancellation, and correlated Langfuse gateway traces.

## Start and use

Start the standalone Keycloak prerequisite, ensure `portal.local` maps to `127.0.0.1`, then run:

```bash
./scripts/phase2/start.sh
```

Open `https://portal.local:8444` and sign in as `alise` or `bob` with local demo password `123456`. Create a conversation, send a message, and revisit it from the sidebar. Conversations persist across normal stops and starts; deletion is intentionally unavailable.

Open Langfuse at `http://localhost:3000`. Sign in with the email in `LANGFUSE_INIT_USER_EMAIL` and the password in `LANGFUSE_INIT_USER_PASSWORD` from the uncommitted `.env`; do not copy either value into logs or commits.

Each turn's correlation ID is also its W3C/Langfuse trace ID. To obtain the latest one without exposing message content:

```bash
docker compose exec -T application-postgres \
  psql -U genai -d genai -Atc \
  'select correlation_id from turns order by created_at desc limit 1'
```

Paste that value into the Langfuse trace/observation search. With the current default, the correlated trace contains the Agentgateway LLM generation and the application Direct-turn span. Ingestion can take a few seconds after the response completes.

## Verify and inspect

```bash
./scripts/phase2/verify.sh
./scripts/phase2/status.sh
```

The live smoke test creates a real direct conversation, checks semantic streaming through the selected model gateway, idempotency, ordered event replay, persisted history, and two-user isolation.

## Stop and recover

```bash
./scripts/phase2/stop.sh
./scripts/phase2/start.sh
```

Inspect failures with:

```bash
docker compose logs --tail=200 portal portal-api agentgateway langfuse-web
```

If startup reports that ports `3000`, `8088`, or `8091` are already allocated, inspect `docker ps` for an older Phase 0 Compose project. Stop only the exact conflicting legacy containers; do not remove their volumes. The Phase 2 and legacy Phase 0 Langfuse deployments may use separate preserved data sets.

Normal stop preserves all application and observability data. Do not use `docker compose down -v` unless intentionally resetting the platform.

## Phase boundary

This historical Phase 2 runbook covers Direct mode only. Temporal-backed Agent mode was delivered in Phase 3, and MCP tools with policy enforcement were delivered in Phase 4; use the later phase runbooks for current operation.
