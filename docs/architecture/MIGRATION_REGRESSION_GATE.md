# Migration Regression Gate

Status: Implemented; accepted for transition Increments 0–1
Last updated: 2026-08-21

## Acceptance result

The complete live command passed successfully on 2026-08-21 against the implemented Bifrost Phase 0–4 baseline:

```bash
./scripts/migration-baseline/verify.sh
```

This accepted run establishes the comparison baseline for subsequent gateway and agent-runtime transition increments. It includes the paid Yandex checks and controlled restarts described below.

The complete command passed again on 2026-08-21 after Increment 1 introduced vendor-neutral `ModelGateway` and `ToolGateway` ports and moved the Bifrost wire contracts into adapters. This second accepted run proves that the gateway seam preserved the frozen Phase 0–4 behavior.

## Purpose

This gate freezes the accepted Phase 0–4 behavior before the Agentgateway and versioned-agent transition. It is the shared go/no-go suite for gateway adapter extraction, Agentgateway compatibility, gateway cutover, and the later generic agent runtime.

Run it against the current Bifrost baseline first and retain the result as comparison evidence. Every transition increment that changes a covered boundary must pass the same behavior through its selected implementation.

## Preconditions

- The standalone Keycloak deployment and local CA are available.
- The complete Phase 4 Compose stack is running and healthy.
- `.env` contains valid Yandex and Langfuse configuration.
- The demo users and passwords described by the phase runbooks are available.
- Docker, `uv`, Node.js, and npm are installed.

Start the baseline stack with:

```bash
./scripts/phase4/start.sh
```

## Run

```bash
./scripts/migration-baseline/verify.sh
```

The live gate intentionally makes paid Yandex requests. It also restarts the diagnostic MCP server, Bifrost, and the Agent worker to prove recovery. Do not run it against an environment where these controlled service restarts would disrupt other users.

## Coverage

| Required behavior | Verification source |
|---|---|
| Responses request, semantic SSE, strict JSON Schema, forced function call, stateless continuation, and usage-compatible response | Phase 0 smoke |
| Bifrost health, MCP discovery/execution, diagnostic MCP restart recovery, and gateway restart/reconnection | Phase 0 smoke |
| Direct portal streaming, idempotency, ordered replay, persistence, cross-user isolation, and Langfuse correlation | Phase 2 smoke |
| Normal no-tool Agent response and Temporal worker restart recovery | Phase 3 smoke |
| One-tool and ordered multi-tool Agent runs, audit persistence, and model/tool trace correlation | Phase 4 smoke |
| Owner cancellation and terminal cancellation replay | Phase 4 smoke |
| Unknown, diagnostic, fabricated, and name-confused tool denial | Phase 4 smoke |
| Invalid JSON, schema-invalid, extra-field, and oversized argument rejection | Portal API unit tests |
| Cross-user conversation, turn, event, cancellation, and tool-audit isolation | Phase 2 and Phase 4 smoke |
| MCP schemas and deterministic tool behavior | Time and MTG MCP unit tests |
| Backend lint/tests, frontend lint/components/build, Compose rendering, and secret policy | Static portion of the migration gate |

## Pass criteria

- Every command exits successfully.
- Each live stream reaches its expected terminal event.
- No denied tool reaches `tool.started`.
- Restarted services reconnect without manual repair.
- A turn correlation ID resolves the required observations in Langfuse.
- The final line is `PASS: complete Bifrost-era migration regression baseline`.

## Accepted runs

| Date | Transition point | Result |
|---|---|---|
| 2026-08-21 | Increment 0 baseline freeze | Passed |
| 2026-08-21 | Increment 1 vendor-neutral gateway seam | Passed |

## Failure handling

Treat a failure as a migration blocker until it is classified as one of:

1. a regression in platform behavior;
2. an unavailable prerequisite or credential;
3. a paid-provider transient with preserved request evidence; or
4. an intentionally approved contract change documented in the transition plan.

Do not weaken an assertion merely to make a replacement gateway pass. If a behavior is deliberately changed, update the transition decision, the acceptance contract, and both old/new comparison evidence together.
