# Porfirium Phase 3 implementation results

Date: 2026-08-16  
Status: Implemented and accepted by the user on 2026-08-16.

## Delivered

- pinned local Temporal server and UI backed by persistent PostgreSQL schemas;
- separately restartable Python Agent worker using versioned `PorfiriumAgentWorkflowV1`;
- durable planning, generation, completion, failure, and cancellation projection into ordered database/SSE events;
- idempotent final-message persistence and retry policies around workflow activities;
- W3C correlation propagation from the durable activity through Bifrost into Langfuse;
- startup enforcement of deny-by-default MCP injection plus defensive rejection of unexpected tool calls before Phase 4;
- Direct LLM / Agent conversation selection with mode-filtered history, Agent progress rendering, and active-run reconnection after browser refresh;
- independent workspace/sidebar scrolling with the user identity and sign-out control pinned in view;
- Phase 3 start, stop, status, smoke, verification, and recovery commands.

## Verified evidence

The live durability smoke test reported:

```text
PASS: durable Agent emitted ordered planning, generation, and completion status
PASS: Agent completed after its Temporal worker was restarted mid-run
PASS: final response persisted and the Temporal workflow is inspectable
```

The worker was restarted after the persisted `planning` event. Temporal retained the durable timer and dispatched the remaining model and completion activities to the restarted worker. The final response was present in conversation history and the completed workflow was queryable by its deterministic workflow ID.

Automated API checks: 6 passed. Frontend checks: lint passed, 1 component test passed, and the production build passed. Compose configuration validation and the existing secret-pattern scan passed.

The Phase 2 live regression smoke also passed: direct Yandex streaming, idempotency, SSE replay, persistence, cross-user isolation, and correlated Langfuse observations remain intact.

A tool-boundary regression was reproduced and corrected after user testing found a persisted Bifrost setting injecting Phase 0 diagnostic tools into Agent v1. The live policy is now repaired and enforced during startup/verification, requests explicitly declare no tools, and the worker defensively handles any unexpected function call. Repeating the failing prompt returned a complete no-tools explanation, including across a worker restart.

## Resource snapshot

Approximate live memory usage after the durability test:

| Component | Memory |
|---|---:|
| Temporal server + UI | 112 MiB |
| Agent worker | 75 MiB |
| Portal + API | 105 MiB |
| Application PostgreSQL (application + Temporal schemas) | 143 MiB |
| Bifrost | 139 MiB |
| Langfuse web + worker | 1.43 GiB |
| ClickHouse | 1.30 GiB |

## Known limitations

- Agent v1 is intentionally a single no-tool model call. Tools and policy arrive in Phase 4.
- Cancellation is durable at the workflow level, but an already-running HTTP model request may consume upstream work before asynchronous cancellation interrupts the activity.
- Temporal shares the application PostgreSQL service for this local demo, using separate `temporal` and `temporal_visibility` databases. Production topology remains deferred.
- The progress vocabulary is fixed to planning, generating, and completed; richer reasoning/tool steps begin in Phase 4.
- A dedicated one-click retry affordance and conversation rename UI remain deferred.
- GitHub Action references remain version-tag pinned pending Phase 5 hardening.

## Phase boundary

Phase 4 introduces the time and MTG catalog MCP servers, explicit tool-call validation, read-only allowlists, execution activities, tool audit events, and prompt-injection security tests.

## Handoff acceptance

The user exercised Agent mode and the updated conversation UI, reported issues that were corrected and regression-tested, and accepted Phase 3 on 2026-08-16.
