# Phase 0 diagnostics runbook

> Historical Phase 0 snapshot. Its Bifrost service, configuration, and smoke scripts were retired in architecture transition Increment 5, so the commands below are retained as evidence and are no longer operational against current `compose.yaml`. Use `docs/phase4/RUNBOOK.md` for current operation.

## Delivered scope

Phase 0 validates the external integration boundaries before portal implementation:

- canonical HTTPS connectivity to standalone Keycloak;
- Yandex OpenAI-compatible Responses API generation, streaming, structured output, and MCP tool loop through Bifrost;
- Bifrost discovery of a local read-only streamable-HTTP MCP server;
- local self-hosted Langfuse health and authenticated trace API access;
- initial image/package license inventory;
- selected MTG catalog set/schema manifest;
- observed host/container resource use.

The new `GenAI-platform` realm and the React/FastAPI portal are Phase 1 work and are intentionally not created here.

## Start

Start standalone Keycloak first if needed:

```bash
cd /home/dvy/Projects/KeyCloak
docker compose -f docker-compose.keycloak.yml up -d
```

Then start Phase 0:

```bash
cd /home/dvy/Projects/genai-demo-platform
./scripts/phase0/start.sh
```

The first start downloads several large Langfuse images and builds the diagnostic MCP image. `bootstrap.sh` generates an uncommitted `.env` with mode `0600`; it never prints generated secrets.

## Verify

```bash
./scripts/phase0/verify.sh
./scripts/phase0/status.sh
./scripts/phase0/licenses.sh
```

The smoke test makes five paid Yandex model requests: basic generation, semantic streaming, strict JSON Schema output, a forced MCP function call, and stateless continuation after the tool result.

Until a current Yandex key is entered in this project's `.env`, reproduce every other check explicitly with:

```bash
./scripts/phase0/verify.sh --skip-yandex
```

This skip is visible in test output and must not be used to claim that the Yandex gate passed. See `docs/phase0/RESULTS.md`.

Expected local interfaces:

| Component | URL | Expected result |
|---|---|---|
| Keycloak | `https://keycloak.local:8443` | Existing standalone login/admin service |
| Bifrost | `http://localhost:8088` | Gateway UI and API |
| Langfuse | `http://localhost:3000` | Local observability UI |
| Diagnostic MCP | `http://localhost:8091/health` | JSON status `ok` |

For Langfuse, use `phase0@example.test` and read `LANGFUSE_INIT_USER_PASSWORD` locally from `.env`. Never share the value in logs, screenshots, or commits.

## Stop and restart

```bash
./scripts/phase0/stop.sh
./scripts/phase0/start.sh
```

Named volumes preserve Bifrost and Langfuse state. No reset command is provided because deleting these volumes is destructive. If a clean reset becomes necessary, resolve and review the exact project volumes before removing them.

## Troubleshooting

Inspect service state and recent logs:

```bash
docker compose ps
docker compose logs --tail=200 bifrost
docker compose logs --tail=200 diagnostic-mcp
docker compose logs --tail=200 langfuse-web langfuse-worker
```

Common causes:

- Keycloak hostname missing: ensure `keycloak.local` resolves to `127.0.0.1` and the existing local CA is trusted.
- Yandex test unavailable: confirm `YANDEX_API_KEY`, `YANDEX_MODEL`, and `YANDEX_OPENAI_BASE_URL` exist in this project's `.env`; do not print them.
- Bifrost has stale configuration: inspect its UI/config API and logs. Config changes are versioned/persisted by Bifrost.
- Langfuse startup is slow: wait for PostgreSQL, ClickHouse, Redis, and MinIO health checks and migrations.
- Port conflict: Phase 0 binds only localhost ports `3000`, `8088`, and `8091`; Keycloak owns `8443` and `8180`.

### Repair persisted MCP injection policy

The declarative configuration disables automatic MCP tool injection. Bifrost also persists client settings in its database, and an older persisted value can override `deploy/bifrost/config.json`. The smoke test detects this condition as:

```text
FAIL Bifrost automatic MCP injection disabled
```

Preserve the complete live client configuration while changing only this setting:

This recovery command requires `jq`.

```bash
curl -sS http://127.0.0.1:8088/api/config \
  | jq '{client_config: (.client_config | .mcp_disable_auto_tool_inject = true)}' \
  | curl -sS -X PUT \
      -H 'Content-Type: application/json' \
      --data-binary @- \
      http://127.0.0.1:8088/api/config
```

Do not send only the changed field: Bifrost validates and replaces the full client configuration. Confirm the live value and rerun verification:

```bash
curl -sS http://127.0.0.1:8088/api/config \
  | jq '.client_config.mcp_disable_auto_tool_inject'
./scripts/phase0/verify.sh
```

The expected value is `true`. Ordinary LLM requests then receive no MCP tools. The trusted backend must explicitly select policy-approved tools with `x-bf-mcp-include-tools`.

## Known Phase 0 limitations

- No portal, new Keycloak realm, conversations, users, or Temporal agent exists yet.
- The standalone Keycloak Compose file currently omits the realm-import volume mount; Phase 0 validates HTTPS through `master`, and Phase 1 must mount the new realm export.
- The diagnostic MCP server is deliberately not one of the final two demo servers.
- MTG records are not imported yet; only the approved set/schema manifest exists.
- The official Langfuse object-store dependency introduces a non-preferred AGPL license. MinIO was accepted as a documented local-demo exception on 2026-08-16; reassess it before production redistribution.
- Portal HTTPS is selected as the preferred direction, but its Caddy configuration arrives with the portal in Phase 1.
