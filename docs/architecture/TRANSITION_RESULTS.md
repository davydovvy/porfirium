# Architecture Transition Results

Status: In progress
Last updated: 2026-08-21

This document records acceptance evidence for the transition from Bifrost to Agentgateway and from the embedded agent implementation to independently publishable, immutable agent versions. The transition scope and exit gates are defined in [Agentgateway and Versioned Agent Platform Transition Plan](AGENTGATEWAY_AGENT_PLATFORM_TRANSITION.md).

## Progress

| Increment | Status | Accepted | Evidence |
|---|---|---|---|
| 0 — Freeze accepted behavior | Complete | 2026-08-21 | [Migration Regression Gate](MIGRATION_REGRESSION_GATE.md) |
| 1 — Vendor-neutral gateway adapters | Complete | 2026-08-21 | Gateway adapter contract suite and complete live migration gate |
| 2 — Agentgateway/Yandex compatibility spike | Complete | 2026-08-21 | Pinned side-by-side deployment and `scripts/agentgateway-spike/verify.sh` |
| 3 — MCP cutover | Not started | — | — |
| 4 — LLM cutover | Not started | — | — |
| 5 — Bifrost retirement | Not started | — | — |
| 6 — Versioned agent catalog | Not started | — | — |
| 7 — Generic Temporal workflow | Not started | — | — |
| 8 — Filesystem/CLI publication | Not started | — | — |
| 9 — Portal agent builder | Not started | — | — |
| 10 — Executable-code isolation | Not started | — | — |

## Increment 0 acceptance

The complete live baseline command passed successfully on 2026-08-21:

```bash
./scripts/migration-baseline/verify.sh
```

The accepted run established the Bifrost Phase 0–4 comparison baseline and exercised:

- backend lint and tests, MCP unit tests, frontend lint/component tests/build, Compose rendering, and secret-policy checks;
- Yandex Responses, semantic SSE streaming, strict structured output, forced function calling, explicit MCP execution, and stateless continuation;
- diagnostic MCP restart recovery and Bifrost restart/reconnection;
- Direct-mode persistence, idempotency, ordered SSE replay, user isolation, and Langfuse correlation;
- no-tool Agent execution and Temporal worker restart recovery;
- one-tool and ordered multi-tool Agent execution with persisted audit records;
- owner cancellation with a replayable terminal event;
- denial of unavailable, fabricated, and name-confused tools; and
- malformed, schema-invalid, unexpected-field, and oversized tool argument rejection.

The run intentionally made paid Yandex requests and performed controlled restarts of `diagnostic-mcp`, `bifrost`, and `agent-worker`.

## Increment 1 acceptance

Increment 1 introduced vendor-neutral `ModelGateway` and `ToolGateway` ports while retaining Bifrost as the active adapter. Focused backend verification passed with 21 tests, including six adapter contract tests. Direct and Agent execution no longer contain Bifrost URLs, headers, SSE parsing, or MCP execution envelopes.

The complete live command passed successfully on 2026-08-21:

```bash
./scripts/migration-baseline/verify.sh
```

The accepted run covered paid Yandex Responses and streaming, structured output, forced and automatic tool calls, stateless continuation, gateway and MCP restart recovery, Direct persistence/replay, Temporal worker recovery, owner cancellation, multi-tool execution, audit/trace correlation, cross-user isolation, and denied-tool security behavior.

## Increment 2 acceptance

Increment 2 was accepted on 2026-08-21 with Agentgateway 1.4.0 pinned by image digest (`sha256:771afaf093065477fa296eb90dcb618a0300165f12a32f80bbdd1427fab900ec`) and running beside Bifrost. Bifrost remains the active application gateway.

The repeatable acceptance command is:

```bash
./scripts/agentgateway-spike/verify.sh
```

It validates the pinned configuration, starts the isolated spike, and proves all eight deterministic prefixed MCP tools, MCP execution and default denial, Yandex Responses usage, semantic SSE, strict JSON Schema, forced function calls, explicit MCP execution, stateless continuation, W3C trace correlation in Langfuse, target restart recovery, and gateway restart recovery. The run makes paid Yandex requests and deliberately restarts `diagnostic-mcp` and `agentgateway-spike`.

Two integration details discovered by the spike are now explicit configuration contracts:

- Agentgateway's synthetic upstream MCP initialization uses the bare Compose service authority, so each FastMCP server allowlist includes that exact internal hostname as well as its normal host-and-port forms.
- Agentgateway interprets OTLP header values as CEL expressions. Compose therefore supplies `OTEL_EXPORTER_OTLP_HEADERS` with the secret value quoted as a CEL string; no Langfuse credential is stored in the tracked YAML.

## Next acceptance target

Increment 3 is the MCP cutover. Its execution order is:

1. Implement standard MCP framing and `tools/list`/`tools/call` in `AgentgatewayToolGateway`.
2. Normalize tool identifiers, successful results, JSON-RPC errors, transport failures, and trace propagation into the existing `ToolGateway` contracts.
3. Add focused coverage for discovery, execution, denial, malformed responses, response bounds, upstream failures, and W3C tracing.
4. Run an explicit `TOOL_GATEWAY_PROVIDER=agentgateway` application canary while model traffic remains on Bifrost.
5. Pass the focused suite, `./scripts/agentgateway-spike/verify.sh`, and the complete `./scripts/migration-baseline/verify.sh` gate.
6. Only then change the default MCP provider to Agentgateway and update the operational documentation.

Bifrost remains deployed as the MCP rollback provider during Increment 3. Rollback is configuration-only (`TOOL_GATEWAY_PROVIDER=bifrost`); Bifrost removal is reserved for Increment 5. LLM cutover is explicitly outside this increment and begins in Increment 4.
