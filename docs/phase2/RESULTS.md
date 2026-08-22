# Porfirium Phase 2 implementation results

> Historical acceptance evidence. Transition Increment 5 retired the Bifrost topology referenced below; current operation uses Agentgateway exclusively.

Date: 2026-08-16  
Status: Implemented and accepted by the user on 2026-08-16.

## Delivered

- persistent, owner-scoped Direct LLM conversations and messages;
- conversation creation, listing, history retrieval, and rename API support without deletion;
- idempotent turn submission with a durable state projection;
- Yandex Responses API semantic streaming through Bifrost;
- persisted, monotonically ordered events with authenticated SSE replay and heartbeats;
- browser streaming, stop control, incomplete-message handling, public errors, and history navigation;
- deterministic turn correlation IDs propagated as W3C trace IDs into Bifrost;
- Phase 2 start, stop, status, smoke, verification, and recovery documentation.

## Verified evidence

The live smoke test reported:

```text
PASS: direct Yandex response streamed through Bifrost
PASS: idempotent turn submission and ordered SSE replay
PASS: persistent history and cross-user isolation
PASS: turn correlation ID locates the complete Bifrost trace in Langfuse
```

The latest correlated Langfuse trace contained 24 observations, including both `GENERATION` and `SPAN` records across the `/v1/responses`, model, key-selection, policy, logging, and telemetry path. Four persisted messages remained present after a portal API restart.

Automated API checks: 6 passed. Frontend checks: lint passed, 1 component test passed, and the production build passed. The secret-pattern scan and Compose configuration validation passed.

## Resource snapshot

Approximate live memory usage after verification:

| Component | Memory |
|---|---:|
| Portal + API | 84 MiB |
| Application PostgreSQL | 45 MiB |
| Bifrost | 137 MiB |
| Langfuse web + worker | 1.33 GiB |
| ClickHouse | 1.22 GiB |
| MinIO + Redis | 107 MiB |

## Known limitations

- Direct-turn execution is process-local. A browser disconnect does not cancel it and event replay works, but restarting the portal API during an active turn leaves that turn interrupted. Durable execution begins with Temporal in Phase 3.
- Cancellation is cooperative and applies to turns running in the current portal API process.
- The UI supports retry by resubmitting a message; a dedicated one-click retry affordance remains to be added.
- Conversation rename is supported by the API but is not yet exposed in the UI.
- The first Phase 2 startup encountered legacy Phase 0 containers occupying public ports. They were stopped without deleting their containers or volumes; the running Phase 2 Langfuse instance uses separate preserved state.
- GitHub Action references remain version-tag pinned pending Phase 5 hardening.

## Phase boundary

At this Phase 2 handoff, Temporal-backed Agent mode was deferred to Phase 3 and MCP tools/policy to Phase 4. Both later increments have since been implemented and accepted.

## Handoff acceptance

The user exercised the portal, confirmed that the increment works, and accepted Phase 2 on 2026-08-16.
