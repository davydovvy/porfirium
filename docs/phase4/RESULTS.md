# Porfirium Phase 4 implementation results

Date: 2026-08-19  
Status: Implemented and accepted by the user on 2026-08-19.

> Transition update (2026-08-22): accepted architecture transition Increment 3 moved current MCP execution from Bifrost to Agentgateway without changing the Phase 4 behavior recorded here. Bifrost remains the model provider and MCP rollback until later transition increments.

## Delivered

- independently packaged, non-root time and MTG catalog MCP services with locked dependencies, health checks, schemas, and deterministic tests;
- a checked-in 100-card catalog spanning M11, ISD, RTR, THS, and KTK, with dated Scryfall nonfoil USD snapshots plus provenance, checksum, and refresh metadata;
- explicit Bifrost MCP client registration while global automatic tool injection remains disabled;
- versioned `tool_assistant_v1` policy with exact-name lookup, JSON Schema validation, read-only classification, bounded arguments/results, and stable denial reasons;
- migration `0004_phase4_tool_audit` and idempotent, owner-scoped durable tool decisions and execution records;
- replay-safe `PorfiriumToolAgentWorkflowV2` alongside the retained V1 workflow;
- bounded model/tool iteration, persisted ordered tool events, one atomic final assistant response, and correlated Langfuse model/tool observations;
- portal rendering and reconnect replay for requested, started, completed, and denied tool steps;
- non-shrinking conversation-history rows that remain distinct when the sidebar scroll list is full;
- Phase 4 start, stop, status, smoke, verification, and operational documentation.

## Verified evidence

The live Phase 4 smoke reported:

```text
PASS: V2 Agent recovered after worker restart at persisted tool authorization
PASS: one tool audit row, one final message, and ordered tool events persisted
PASS: the turn correlation ID locates model and tool observations in Langfuse
PASS: a second user could not list, read, stream, or cancel Alice's tool turn
PASS: conversation, turn, and tool-request identifiers remained owner-isolated
PASS: MTG Agent completed search, detail, comparison, and price synthesis
PASS: three ordered MTG tool calls and audit records persisted
PASS: prompt injection could not start diagnostic, fabricated, or confused tools
PASS: any model-proposed unauthorized calls were durably denied
```

The worker was restarted after the time tool authorization was persisted. The same V2 workflow resumed and completed with exactly one completed audit row and final assistant message. The MTG run performed search, detail, and comparison calls in order. A prompt demanding diagnostic, fabricated, and name-confused tools caused no unauthorized execution; any proposed calls were durably denied.

Langfuse was inspected directly after acceptance. A no-tool Agent regression run contained 25 observations with one distinct trace ID equal to its turn correlation ID. The Phase 4 time run placed Bifrost generation/plugin observations, MCP execution, the tool observation, and application observations under the same correlation/trace ID; the Langfuse session ID matched it as well.

Automated checks passed on 2026-08-19: time MCP 6 tests, MTG MCP 5 tests, backend Ruff plus 15 tests, frontend lint plus 1 component test and production build, Compose configuration validation, secret-pattern scan, and Bifrost deny-by-default policy validation.

The Phase 3-style no-tool durability regression passed through the current Agent route across an `agent-worker` restart. This preserves the user-visible Phase 3 behavior but is not a new V1-history replay test. The Phase 2 Direct regression passed streaming, idempotency, ordered SSE replay, persistence, cross-user isolation, and correlated Langfuse tracing.

## Known limitations

- All Phase 4 tools are reviewed read-only demo tools; side effects and interactive approvals are deferred.
- Catalog prices are dated Scryfall nonfoil USD snapshots, not live quotes or purchasing advice. Physical condition is unspecified, and the catalog contains no inventory quantity field.
- MCP services use private service networking without delegated end-user credentials. The workflow contracts reserve an opaque delegated-credential reference for a future audience-restricted token-exchange integration.
- Cancellation is durable between activities, but already-running upstream HTTP work may finish before asynchronous cancellation takes effect.
- Broader dependency-failure, load, resource, and demo hardening remains Phase 5 work.
- The MCP framework currently emits a Pydantic incomplete-forward-reference warning during unit startup; tool behavior and tests are unaffected.
- GitHub Action references remain version-tag pinned pending Phase 5 hardening.

## Phase boundary

Phase 5 covers clean-checkout demo hardening, broader failure and load tests, production-gap documentation, dependency/security tightening, and the complete scripted demonstration.

## Handoff acceptance

The user exercised the Phase 4 Agent and conversation UI, confirmed that everything works, and accepted Phase 4 on 2026-08-19.
