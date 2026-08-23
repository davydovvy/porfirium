# Increment 6.5 — Legacy Temporal runtime retirement plan

Status: Implemented; awaiting user acceptance  
Position: After accepted Increment 6 and before Increment 7  
Purpose: Remove the legacy Temporal compatibility burden before introducing the generic runtime

## Outcome

Increment 6.5 retires the current release-specific Temporal execution plane before Increment 7
introduces `AgentRunWorkflow`. It stops new Agent turns, drains or safely terminates every open
legacy execution, proves that no workflow still depends on the legacy poller, and removes the
legacy queue configuration, worker service, workflow registrations, and live operational paths.

After this task, Direct mode remains available but Agent turn creation returns an explicit
maintenance response until Increment 7 deploys the generic runtime. This maintenance interval
is deliberate and must be kept short by implementing and releasing 6.5 and 7 in the same
coordinated change window.

No published agent, run snapshot, workflow history, audit record, event, or conversation is
deleted. Historical source or replay fixtures may remain in a non-runtime compatibility area,
but no deployed process polls or starts the legacy workflows.

## Scope

Included:

- an Agent execution maintenance gate at turn acceptance;
- inventory and classification of all V1/V2 Temporal executions;
- graceful completion or explicit cancellation of every open legacy execution;
- proof that no accepted/running database turn or open Temporal execution requires the queue;
- removal of `TEMPORAL_TASK_QUEUE` and `porfirium-agent-v1` from live configuration;
- removal of the `agent-worker` Compose service and its operational script dependencies;
- removal of V1/V2 workflow and activity registration from executable worker startup;
- prevention of new starts for `PorfiriumAgentWorkflowV1` and
  `PorfiriumToolAgentWorkflowV2`;
- preservation of historical data and replay evidence;
- a clean retirement verification script and rollback procedure.

Deferred to Increment 7:

- `AgentRunWorkflow` and generic activities;
- the generic task queue and worker service;
- manifest schema v2 and `tool-assistant:1.1.0`;
- re-enabling Agent turn acceptance;
- execution of existing or new conversations through the generic runtime.

## Fixed design decisions

1. Retirement uses a drain, not history deletion. Temporal namespaces, histories, database
   turns, messages, events, audits, snapshots, and published versions remain intact.
2. New Agent turns are disabled before the inventory is captured. Direct turns are unaffected.
3. An execution is safe to drain only when both Temporal and application state are inspected;
   database state alone is insufficient.
4. Open legacy executions are allowed to complete within a documented bounded drain interval.
   Executions that do not complete are cancelled through the existing owner/platform-safe
   cancellation path and must reach a durable terminal state.
5. The legacy worker is stopped only after the zero-open-execution gate passes.
6. `tool-assistant:1.0.0` remains an immutable historical publication. Retirement changes
   runtime availability, not its content or digest.
7. Existing conversations remain pinned to `1.0.0` during maintenance. Increment 7 must define
   their explicit upgrade behavior before Agent execution is re-enabled.
8. Completed histories do not justify a continuously running worker. Replay compatibility is
   retained through checked-in history fixtures/tests or isolated historical code, not a live
   queue poller.
9. Rollback may temporarily restore the exact legacy worker image/configuration, but it may not
   rewrite histories or start replacement workflows with reused IDs.
10. The task is not accepted while any API, script, health check, documentation, or Compose
    dependency still assumes a live legacy worker.

## Maintenance contract

Add an explicit server-side Agent execution state, configured as
`AGENT_EXECUTION_MODE=maintenance` for this task. While active:

- catalog and conversation read APIs remain available;
- Direct conversation creation and turns remain available;
- existing Agent conversations and their persisted history remain readable;
- new Agent conversation creation may remain available for catalog inspection, but starting an
  Agent turn returns HTTP `503` with stable code `agent_runtime_maintenance`;
- no turn, user message, run snapshot, event, or workflow is created for a rejected request;
- idempotency retries return the same maintenance outcome and cannot enqueue work;
- the portal disables Agent submission with a clear maintenance label rather than leaving a
  turn pending;
- readiness distinguishes “API healthy, Agent runtime intentionally unavailable” from an
  unexpected dependency failure.

The maintenance setting is fail-closed: an unknown value must not fall back to legacy routing.
Increment 7 replaces this temporary two-state switch with the generic runtime readiness gate.

## Legacy execution inventory

The retirement script must query Temporal for open executions of both workflow types:

- `PorfiriumAgentWorkflowV1`;
- `PorfiriumToolAgentWorkflowV2`.

It must also query application turns in `accepted` or `running` state and reconcile by workflow
ID. The report contains only safe identifiers and states:

- workflow ID and run ID;
- workflow type and task queue;
- Temporal execution status;
- turn ID, owner-safe correlation ID, and application state;
- snapshot ID/version/digest when present;
- last durable event type and sequence;
- reconciliation result: matched, Temporal-only, database-only, or terminal mismatch.

The script exits nonzero for any mismatch until it has been resolved or documented as a tested
historical exception. It must not print prompts, tool arguments/results, tokens, or secrets.

## Drain and retirement sequence

### Task 6.5.1 — Capture the rollback baseline

- record the deployed image digest, Compose rendering, queue name, workflow/activity
  registrations, Temporal namespace/retention, migration revision, and default agent release;
- run the current migration baseline, Agentgateway compatibility gate, and Phase 4 verification;
- export a bounded inventory of open and recently completed V1/V2 histories;
- create or refresh sanitized replay fixtures for both legacy workflow types where practical.

Checkpoint: the exact pre-retirement runtime can be reconstructed without modifying data.

### Task 6.5.2 — Close admission

- add and enable `AGENT_EXECUTION_MODE=maintenance`;
- fail Agent turn creation before snapshot, message, event, or workflow persistence;
- expose the stable maintenance state in API readiness/status and the portal;
- prove Direct mode and read-only Agent history/catalog views still work;
- rerun concurrent submission/idempotency tests to prove no request crosses the gate.

Checkpoint: repeated Agent submissions create zero new turns and zero Temporal executions.

### Task 6.5.3 — Drain open executions

- run the reconciled inventory after admission is closed;
- allow healthy open V1/V2 executions to complete for the documented drain interval;
- exercise worker-restart recovery during the drain if an execution is open;
- cancel any remaining execution through the supported cancellation path;
- repair no state manually unless a separate reviewed recovery procedure records the reason;
- repeat inventory until Temporal has zero open V1/V2 executions and the database has zero
  `accepted`/`running` Agent turns.

Checkpoint: two consecutive inventory runs separated by at least one poll interval report zero
open legacy work and no reconciliation mismatches.

### Task 6.5.4 — Remove the live legacy runtime

- stop the legacy worker only after the zero-open gate;
- remove the `agent-worker` Compose service;
- remove `TEMPORAL_TASK_QUEUE`/`porfirium-agent-v1` from API and worker configuration;
- remove workflow start calls for V1/V2 from the API;
- remove legacy worker startup and registration from runtime entry points;
- move any retained workflow definitions and replay helpers out of production imports, or keep
  them clearly isolated and unreachable from application startup;
- update start, stop, status, smoke, and verification scripts so none expects a legacy poller;
- ensure no health check or dependency prevents the API/portal from running in maintenance.

Checkpoint: the rendered Compose model contains no Agent worker or legacy queue setting, and
repository search finds no production start/registration path for either legacy workflow.

### Task 6.5.5 — Retirement verification and handoff

- restart the stack from the documented clean procedure without an Agent worker;
- prove API, portal, authentication, database, Temporal, Agentgateway, MCP services, Langfuse,
  and Direct mode remain healthy;
- prove Agent submission fails immediately and cleanly with `agent_runtime_maintenance`;
- prove historical conversations, events, snapshots, and tool audits remain readable and
  owner-isolated;
- prove no Temporal poller exists for `porfirium-agent-v1` and no new V1/V2 execution appears;
- document the final inventory, removed surfaces, maintenance behavior, and rollback command;
- hand Increment 7 a zero-legacy-runtime baseline.

Checkpoint: the retirement verification script passes twice, including after a full service
restart.

## Test and acceptance matrix

### Automated tests

- maintenance mode rejects Agent turns before any database write or Temporal call;
- Direct mode remains unchanged;
- unknown execution-mode configuration fails closed;
- duplicate/idempotent Agent submissions during maintenance create no records;
- catalog and historical Agent conversation/event reads remain available and owner-scoped;
- cancellation and drain reconciliation normalize Temporal/application terminal states;
- inventory detects Temporal-only, database-only, workflow-type, and state mismatches;
- legacy manifest v1 and `tool-assistant:1.0.0` digest validation remain intact;
- sanitized V1/V2 replay fixtures remain deterministic if historical replay support is kept;
- Compose/config tests reject reintroduction of the legacy queue or worker.

### Live acceptance

1. Run the complete current gates before admission closes to establish a green baseline.
2. Enable maintenance while attempting concurrent Agent submissions; require stable `503`
   responses and zero new turns, snapshots, messages, events, or workflows.
3. Drain any open workflow and reconcile Temporal with the application database.
4. Remove/restart the worker and prove two consecutive checks report zero open V1/V2 work and
   zero legacy pollers.
5. Restart the complete remaining stack and prove Direct mode, authentication, persistence,
   replay, isolation, Agentgateway, and tracing still pass.
6. Read previously completed Agent conversations and audit/event histories as their owner, and
   prove another user still receives non-enumerating denial.
7. Attempt a new Agent turn from both API and portal; require the explicit maintenance outcome
   with no pending UI state.
8. Render Compose and scan runtime configuration/source; require no live reference to
   `porfirium-agent-v1`, V1/V2 start calls, or an Agent worker service.

## Rollback

Rollback is allowed only before Increment 7 accepts generic turns:

1. keep Agent admission closed;
2. restore the recorded legacy worker image, exact queue configuration, and registration code;
3. verify a poller is present on `porfirium-agent-v1`;
4. run one controlled `tool-assistant:1.0.0` canary and the Phase 4 regression gate;
5. reopen Agent admission only after the legacy canary passes.

Do not roll back by deleting Temporal state, changing workflow IDs, mutating published manifests
or snapshots, or marking nonterminal turns complete in SQL.

## Definition of done

- Agent admission is explicitly closed with no partial persistence;
- Temporal and the application database report zero open V1/V2 executions/turns;
- no deployed worker polls `porfirium-agent-v1`;
- no production API path starts `PorfiriumAgentWorkflowV1` or
  `PorfiriumToolAgentWorkflowV2`;
- Compose and operational scripts contain no live legacy worker or queue dependency;
- completed histories, snapshots, events, audits, and published `1.0.0` data remain intact;
- Direct mode and the non-Agent platform remain healthy;
- historical replay evidence is retained without a live compatibility worker;
- the retirement verification and rollback rehearsal pass;
- Increment 7 begins from a documented maintenance state with no legacy runtime to preserve.

## Expected changed surfaces

- `apps/portal-api/portal_api/main.py`: pre-persistence maintenance gate and removal of legacy
  start routing;
- `apps/portal-api/portal_api/config.py`: explicit temporary execution mode and removal of the
  legacy task-queue setting;
- `apps/portal-api/portal_api/agent.py` and `worker.py`: production registration removal and
  optional isolation of replay-only definitions;
- `apps/web/src/App.tsx`: visible Agent maintenance state and disabled submission;
- `compose.yaml`: removal of the legacy Agent worker and queue environment;
- phase/migration scripts plus a new legacy inventory/retirement verifier;
- runbook, README, transition status, and retirement results after acceptance.
