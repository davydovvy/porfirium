# Phase 0 implementation results

> Historical Phase 0 snapshot. Deferred Phase 1 identity and portal work has since been implemented; see `docs/phase1/RESULTS.md`.

Date: 2026-08-15  
Status: Complete, runnable, and verified.

## Working results

The Phase 0 stack is running locally with eight healthy/running services:

- Bifrost v1.6.11, pinned by image digest;
- diagnostic read-only MCP server using Python MCP SDK 1.29.0;
- Langfuse 3.225.2 web and worker;
- PostgreSQL, ClickHouse, Redis 7.2.5, and MinIO backing services.

Verified results:

| Check | Result |
|---|---|
| Keycloak canonical HTTPS and trusted local CA | Pass through live `master` discovery |
| Diagnostic MCP health | Pass |
| Bifrost health | Pass |
| Bifrost MCP discovery | Pass: `phase0_diagnostic` connected with two tools |
| Explicit read-only tool execution through Bifrost | Pass: `phase0_diagnostic-echo` returned the expected result |
| Langfuse health and generated local login | Pass |
| Bifrost OTLP export to Langfuse | Pass: authenticated observations are visible after Responses tests |
| Bifrost restart and MCP reconnection | Pass |
| Yandex Responses API through Bifrost | Pass |
| Responses semantic SSE streaming | Pass: typed text-delta and completion events |
| Responses strict JSON Schema output | Pass |
| Responses forced MCP function call and execution | Pass |
| Stateless function-result continuation | Pass without provider-side conversation state |
| MTG manifest | Pass: five selected sets × 20 planned records = 100 |
| Static JSON, Compose, and Python syntax checks | Pass |

The complete suite can be reproduced with:

```bash
./scripts/phase0/verify.sh
```

It intentionally makes five paid requests: basic Responses generation, streaming, JSON Schema output, a forced MCP function call, and stateless continuation after the tool result. For local checks that must not incur model usage, run `./scripts/phase0/verify.sh --skip-yandex`; that mode does not constitute full Phase 0 verification.

## Yandex configuration

Yandex configuration is project-local in the ignored `.env`. The API key was not printed or copied into a tracked file. After changing it, reload Bifrost and verify with:

```bash
docker compose up -d --force-recreate bifrost
./scripts/phase0/verify.sh
```

## Keycloak finding

The standalone Keycloak deployment is healthy, but its current Compose file does not mount `keycloak/mcp-gateway-realm.json` into Keycloak's import directory. On the fresh volume only `master` exists. Phase 1 must add and mount the new `GenAI-platform` realm export before relying on realm bootstrap.

## Resource snapshot

Idle/diagnostic snapshot from the delivered stack:

| Service | Approximate memory |
|---|---:|
| Bifrost | 219 MiB |
| Diagnostic MCP | 46 MiB |
| ClickHouse | 1.09 GiB |
| MinIO | 85 MiB |
| PostgreSQL | 65 MiB |
| Redis | 10 MiB |
| Langfuse web | 934 MiB |
| Langfuse worker | 430 MiB |

Total observed container memory was approximately 2.9 GiB, varying with startup/migrations. No CPU or RAM limits are applied.

## Discovered integration constraints

- Bifrost MCP client names cannot contain hyphens.
- Bifrost exposes external tools using `clientName-toolName`; explicit execution also requires the `x-bf-mcp-include-tools` allowlist under current deny-by-default behavior.
- Python MCP SDK DNS-rebinding protection must explicitly trust the internal Docker host name.
- The current Langfuse image binds its web process to the container hostname, so its internal health probe cannot use loopback.
- Bifrost plugin configuration persisted in its database requires a higher plugin `version` for declarative overrides.
- Yandex is configured as a named OpenAI-compatible Bifrost provider with explicit `/v1/responses` and `/v1/chat/completions` path overrides. Bifrost's standard OpenAI provider route returned 404 even though the same credential/model succeeded directly.
- Responses API is the canonical project contract; Chat Completions remains enabled as fallback.
- Automatic MCP injection is disabled. Callers must explicitly allow tools with `x-bf-mcp-include-tools` after server-side policy evaluation.
- Bifrost persists client settings in its database. The smoke suite verifies the live MCP-injection policy, and the runbook documents a full-client-config repair that preserves unrelated settings.
- Langfuse 3.225.2 exposes the compatible observations read endpoint at `/api/public/observations`.

## Known limitations

- The new Keycloak realm, portal, Temporal, final time MCP server, and MTG catalog server are later phases.
- Only the MTG schema/set manifest exists; card records and source/IP review are not Phase 0 deliverables.
- MinIO is a documented non-preferred-license exception in the official Langfuse dependency shape; the user accepted it for the local demo on 2026-08-16.
