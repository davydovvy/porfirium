# Architecture Transition Results

Status: In progress
Last updated: 2026-08-22

This document records acceptance evidence for the transition from Bifrost to Agentgateway and from the embedded agent implementation to independently publishable, immutable agent versions. The transition scope and exit gates are defined in [Agentgateway and Versioned Agent Platform Transition Plan](AGENTGATEWAY_AGENT_PLATFORM_TRANSITION.md).

Increment sections describe the topology as it existed at each acceptance checkpoint. Statements that Bifrost was active or available for rollback are historical and were superseded by Increment 5.

## Progress

| Increment | Status | Accepted | Evidence |
|---|---|---|---|
| 0 — Freeze accepted behavior | Complete | 2026-08-21 | [Migration Regression Gate](MIGRATION_REGRESSION_GATE.md) |
| 1 — Vendor-neutral gateway adapters | Complete | 2026-08-21 | Gateway adapter contract suite and complete live migration gate |
| 2 — Agentgateway/Yandex compatibility spike | Complete | 2026-08-21 | Pinned side-by-side deployment and `scripts/agentgateway-spike/verify.sh` |
| 3 — MCP cutover | Complete | 2026-08-22 | Agentgateway adapter suite, spike gate, and default-provider migration gate |
| 4 — LLM cutover | Complete | 2026-08-22 | Agentgateway model adapter suite, spike gate, and complete application canary |
| 5 — Bifrost retirement | Complete | 2026-08-22 | Bifrost-free Compose, adapter suite, and complete live gates |
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

## Increment 3 acceptance

Increment 3 added `AgentgatewayToolGateway` with standard MCP initialization, initialized notification and session propagation, JSON-RPC/SSE normalization, stable platform-to-gateway tool-name mapping, result bounds, normalized failures, and W3C trace propagation. Focused backend verification passes with 27 tests.

Both required live commands passed on 2026-08-22. The complete migration regression gate ran without provider overrides, with `TOOL_GATEWAY_PROVIDER=agentgateway` and `MODEL_GATEWAY_PROVIDER=bifrost` selected by the committed defaults. It covered Direct and durable Agent behavior, one-tool and multi-tool execution, audit/event persistence, denial, cancellation, user isolation, worker recovery, and Langfuse correlation. The pinned Agentgateway spike passed its MCP, model, authorization, trace, target-restart, and gateway-restart contracts. During repeated local runs, Docker's published localhost port briefly lagged the healthy internal service after restart; the recovery assertion now checks the runtime Compose network directly and confirms the complete eight-tool inventory.

At the Increment 3 checkpoint, Agentgateway became the default MCP provider while Bifrost remained deployed for model traffic and MCP rollback. No Bifrost path was removed in that increment.

## Next acceptance target

Increment 6 adds the versioned agent catalog, immutable release/digest rules, run pinning, and the first packaged `tool_assistant_v1` release.

## Increment 4 acceptance

Increment 4 added `AgentgatewayModelGateway` with non-streaming and semantic SSE Responses support, explicit policy-approved function definitions, stable model-alias translation, structured output and stateless continuation passthrough, normalized failures, usage preservation, and W3C trace propagation. Focused backend verification passes with 31 tests.

The pinned Agentgateway/Yandex spike passed Responses, semantic streaming, strict JSON Schema, forced function calls, stateless continuation, usage, tracing, and restart recovery. The application canary passed Direct streaming, persistence, idempotency, replay, isolation, and correlated Langfuse `GENERATION`/`SPAN` observations. Durable Agent smoke passed worker recovery, one-tool and ordered multi-tool execution, audit/event persistence, cancellation, owner isolation, and denial of diagnostic, fabricated, and name-confused tools. At the Increment 4 checkpoint, Agentgateway became the committed model default while Bifrost remained the configuration-only rollback pending Increment 5.

## Increment 5 acceptance

Increment 5 removed the Bifrost service, volume declaration, configuration, application adapters, provider-selection environment variables, policy repair script, legacy adapter tests, and current operational references. The Agentgateway Compose service now uses its production name, and all FastMCP origin allowlists and application defaults follow it. Historical Phase 0–4 evidence remains intact and explicitly historical.

The focused backend suite passes with 25 tests, frontend lint/component/build checks pass, and Compose renders without a Bifrost image, service, dependency, environment variable, or volume declaration. The pinned Agentgateway compatibility gate and complete Direct/durable Agent smoke suites pass without Bifrost running. The pre-existing local Bifrost volume was not deleted and is outside the current Compose model.
