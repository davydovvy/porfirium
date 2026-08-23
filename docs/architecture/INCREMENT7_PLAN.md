# Increment 7 — Generic versioned agent runtime plan

Status: Implemented on 2026-08-23; final live acceptance pending  
Target milestone: M3 — Versioned agent runtime  
Prerequisite: Increment 6.5 legacy runtime retirement accepted  

## Outcome

Increment 7 introduces one platform-owned `AgentRunWorkflow` after Increment 6.5 has removed
the release-specific execution plane. The workflow executes only the immutable contract
captured when the turn was accepted. Prompts, model selection, tool grants, and execution limits
do not come from worker constants.

The accepted `tool-assistant:1.0.0` release and completed V1/V2 histories remain immutable
historical records, but no legacy worker or queue returns. A new `tool-assistant:1.1.0` release
exercises the generic runtime. Existing conversations receive an explicit, transactional
upgrade path from the retired `1.0.0` runtime before Agent submission is re-enabled.

This increment completes M3 when two pinned agent versions can execute through the same generic
workflow and an active run survives both a worker restart and publication of a newer release
without changing its behavior.

## Scope

Included:

- a deterministic, version-neutral `AgentRunWorkflow`;
- generic activity contracts that resolve behavior from an immutable run snapshot;
- one generic-runtime Temporal task queue and worker;
- an explicit upgrade path for conversations pinned to the retired runtime;
- a manifest/runtime contract for generic declarative agents;
- a published `tool-assistant:1.1.0` compatibility release;
- snapshot-backed prompts, model alias, tool definitions/grants, and limits;
- unit, integration, replay, restart, concurrency, authorization, and live regression gates;
- operational and rollback documentation for the generic worker and maintenance fallback.

Deferred:

- filesystem/CLI validation and publication, which belongs to Increment 8;
- portal draft authoring and publication, which belongs to Increment 9;
- arbitrary executable agent code and runner isolation, which belong to Increment 10;
- new tool capabilities, approval-required tools, delegated credentials, and live catalog data;
- deletion of published artifacts or completed historical data.

## Fixed design decisions

1. `AgentRunWorkflow` is platform-owned. Agent packages select the supported declarative
   runtime contract; they do not provide or register Temporal workflow code.
2. Workflow input contains stable identifiers only: `turn_id` and `run_snapshot_id`. The first
   activity validates that the identifiers still match and returns a bounded execution plan.
3. The accepted run snapshot is the sole behavioral authority. The worker must not dynamically
   re-resolve an agent version, default release, current model alias, publication status, or tool
   grant.
4. The generic workflow receives the loop bounds it needs from the initial execution plan and
   uses those values deterministically. Activities enforce the same limits independently at
   each I/O boundary.
5. Activities have version-neutral names and accept only typed, bounded contracts.
6. The sole Agent queue is `porfirium-agent-runtime-v1`. Increment 7 must not restore
   `porfirium-agent-v1` or either retired workflow registration.
7. New generic releases declare `runtime.kind = "declarative"` and
   `runtime.contract_version = 1`. They do not name a Python class or arbitrary workflow.
8. The immutable `tool-assistant:1.0.0` package remains a historical legacy release. A new
   `tool-assistant:1.1.0` package carries equivalent user-visible behavior using the generic
   runtime contract. A transactional catalog operation upgrades existing conversation
   selections only with explicit audit evidence; immutable completed run snapshots are never
   changed.
9. Workflow IDs retain `porfirium-agent-<turn-id>`. Workflow type, task queue, snapshot ID,
   agent version, digest, and runtime contract are recorded separately for diagnosis.
10. Tool authorization remains application-owned and fail-closed. Snapshot grants narrow the
    centrally reviewed tool catalog and schema; model output and manifest text never grant
    authority.
11. Use Temporal worker build IDs/deployment versioning if supported by the pinned SDK and local
    server without weakening the clean-checkout gate. This versions future generic-worker
    changes; it is not a reason to restore a legacy queue.
12. No database or artifact cleanup is part of rollout or rollback.

## Target execution contract

The snapshot created at turn acceptance must contain a complete, bounded contract sufficient
for execution after a newer release is published:

```json
{
  "contract_version": 1,
  "agent": {
    "id": "tool-assistant",
    "version": "1.1.0",
    "version_id": "<uuid>",
    "digest": "sha256:<digest>"
  },
  "runtime": {
    "kind": "declarative",
    "contract_version": 1
  },
  "instructions": "<bounded instructions>",
  "model": {
    "alias": "default",
    "provider": "yandex",
    "model": "<resolved immutable target>"
  },
  "tools": [
    {
      "stable_name": "demo_time-get_current_time",
      "schema_version": "1",
      "read_only": true,
      "definition": "<bounded reviewed function schema>"
    }
  ],
  "limits": {
    "max_iterations": 4,
    "max_tool_calls_per_step": 2,
    "max_tool_argument_bytes": 4096,
    "max_tool_result_bytes": 32768,
    "max_output_tokens": 2048
  }
}
```

The exact JSON representation may follow existing model conventions, but these semantics are
required:

- the snapshot is self-contained and immutable after the turn is accepted;
- its digest and agent identity match the published release used at acceptance;
- the resolved model target cannot drift when a model alias is later edited;
- tool definitions are the reviewed schemas used for that run, not current discovery results;
- every list, string, schema, and numeric limit is bounded and validated before persistence;
- secrets and credentials are prohibited.

If an accepted snapshot is absent, malformed, inconsistent with the turn, or uses an unsupported
contract version, the run fails non-retryably with a stable safe error. It must not fall back to
worker defaults or the latest catalog state.

## Generic workflow and activities

`AgentRunWorkflow` performs only deterministic orchestration:

1. Call `load_agent_run_plan(turn_id, run_snapshot_id)` and validate the returned bounded plan.
2. Call `mark_agent_run_running` idempotently.
3. For `0 .. max_iterations - 1`, call `generate_agent_run_step` with the turn, snapshot,
   iteration, and bounded plan metadata.
4. If the step contains final text, call `complete_agent_run` atomically and return it.
5. Otherwise, require one or more tool calls no greater than the snapshot limit.
6. For each call, invoke `authorize_agent_run_tool`, persist the decision, execute an allowed
   call through `execute_agent_run_tool`, and finalize it through
   `record_agent_run_tool_result`.
7. Continue with persisted completed tool results until final text is produced or a limit is
   reached.
8. On controlled activity or contract failure, call `fail_agent_run` idempotently and rethrow.
9. Preserve cancellation semantics and never overwrite a completed or cancelled turn.

The initial plan returned to workflow code contains only values needed for deterministic
branching, such as contract version and loop/call limits. Prompts, histories, tool schemas,
results, provider payloads, and database objects remain inside activities or are returned only
as bounded normalized values.

Activity responsibilities:

- `load_agent_run_plan`: validate turn/snapshot binding, contract version, identity, digest,
  runtime kind, and limits;
- `generate_agent_run_step`: construct model input from persisted conversation and completed
  calls, using only snapshot instructions, resolved model, output limit, and tool definitions;
- `authorize_agent_run_tool`: validate exact snapshot grant, reviewed platform tool identity,
  schema version, read-only classification, arguments, byte limits, and idempotency key before
  execution;
- `execute_agent_run_tool`: use the snapshot result limit and the existing `ToolGateway`, with
  idempotent audit state transitions and normalized retry behavior;
- completion/failure activities: preserve the existing single final assistant message and
  ordered replayable event contract.

Generic activity metadata and Langfuse observations include `turn_id`, correlation ID,
snapshot ID, agent ID/version/digest, runtime contract version, iteration, and tool request ID
where applicable. They must not include credentials or unbounded provider payloads.

## Manifest and catalog evolution

Add manifest schema version 2 for generic declarative releases while retaining validation of
the already-published schema version 1 package:

```json
"runtime": {
  "kind": "declarative",
  "contract_version": 1
}
```

Schema version 2 also includes `max_output_tokens` in `limits`. Publication validation must
reject unknown runtime kinds, unsupported contract versions, arbitrary workflow names, missing
limits, unreviewed tools, and mismatched package identity. Digest calculation remains canonical
over the complete manifest.

Add an additive migration/publication seed for `tool-assistant:1.1.0`. It uses the same six
read-only tools and materially equivalent instructions, with wording or a harmless bounded
limit difference that makes the release digest distinct and lets verification prove which
snapshot executed. Make `1.1.0` the default for newly created Agent conversations only after
the generic worker is healthy. Upgrade eligible conversation selections from `1.0.0` in one
audited transaction, but never rewrite a completed or accepted run snapshot.

No published row or grant is updated in place. If snapshot immutability is not currently
enforced by the database, add a trigger that rejects snapshot update/delete operations after
creation, and test it explicitly.

## Routing and compatibility

Replace the temporary Increment 6.5 maintenance state with one explicit configuration:

- `TEMPORAL_AGENT_RUN_TASK_QUEUE=porfirium-agent-runtime-v1`.

Run one `agent-worker` Compose service registering only `AgentRunWorkflow` and its generic
activities. Readiness must prove that a poller is available before Agent admission changes from
maintenance to generic.

Turn acceptance routes every supported declarative release to `AgentRunWorkflow` on the generic
queue. A legacy, unknown, disabled, or unsupported runtime is rejected before the turn is
committed as accepted. No runtime field may select a Python workflow class.

The API must start a workflow only after the snapshot and user message commit. If Temporal start
fails, retain the current durable failure event behavior. Repeated idempotency keys must not
create another snapshot, turn, message, or workflow.

Completed legacy histories remain discoverable in Temporal and through application history, but
they have no live poller. Replay-only fixtures or isolated historical definitions remain outside
production startup.

## Implementation sequence

### Increment 7.1 — Contracts and snapshot closure

- define typed manifest-v2, run-snapshot, execution-plan, model-step, and tool-call contracts;
- add backward-compatible manifest validation and package digest tests;
- close every worker-constant leak by adding resolved model, tool definitions, and all limits
  to the acceptance snapshot;
- validate size bounds, identity/digest consistency, and unsupported contract failures;
- add database-enforced run-snapshot immutability if it is absent.

Checkpoint: a generic run can be reconstructed from its snapshot with catalog defaults and
worker constants deliberately changed, and malformed snapshots fail closed.

### Increment 7.2 — Generic orchestration and activities

- add `AgentRunWorkflow` under a new workflow type name;
- add version-neutral activities and typed payloads;
- move iteration, per-step call, argument, result, and output-token limits to the snapshot;
- preserve audit idempotency, event ordering, cancellation, atomic completion, and tracing;
- add deterministic workflow tests and activity tests for final-only, single-tool,
  multi-tool, denial, malformed calls, retry, cancellation, and limit exhaustion.

Checkpoint: deterministic tests execute two different snapshot contracts through the same
workflow code with no agent-specific worker branch.

### Increment 7.3 — Generic routing and admission reopening

- add the generic task-queue setting and sole generic worker service;
- route every supported declarative release to the fixed generic workflow and queue;
- reject retired schema-1 runtime execution without restoring legacy registration;
- add replay-only tests using retained V1/V2 fixtures outside production startup;
- transactionally upgrade eligible existing conversation selections from `1.0.0` to `1.1.0`,
  recording counts and leaving completed run snapshots untouched;
- reopen Agent admission only after worker readiness and a controlled canary pass.

Checkpoint: no legacy poller exists, upgraded and newly created conversations execute through
the generic queue, and restarting the generic worker recovers accepted work.

### Increment 7.4 — Second release and pinning proof

- package and validate `tool-assistant:1.1.0` as manifest schema 2;
- publish it through an additive migration using the same catalog invariants as Increment 6;
- retain `1.0.0` as historical catalog data but prevent new execution of its retired runtime;
- make `1.1.0` the default only after readiness checks pass;
- add a verification-only, transactionally validated catalog fixture for a distinct newer
  release/default; this exercises publication drift without exposing the Increment 8 CLI or an
  unsupported product publication endpoint;
- start a `1.1.0` run, pause/restart after durable tool authorization, publish or activate a
  distinct newer release/default, and prove the active run still uses its original snapshot.

Checkpoint: catalog, database, workflow metadata, events, audits, and traces all identify the
same pinned version and digest before and after publication/default changes.

### Increment 7.5 — Full regression and handoff

- extend the migration baseline and Phase 4 verification without weakening their assertions;
- add an Increment 7 live smoke for two generic versions, restart, publication drift,
  denial, isolation, and trace correlation;
- run backend lint/tests, frontend lint/component/build, Compose validation, secret scanning,
  Agentgateway compatibility, and the complete current live suite;
- update README, transition status, runbook, and Increment 7 results only after acceptance.

Checkpoint: the complete exit gate passes from the documented clean start procedure.

## Test and acceptance matrix

### Automated tests

- manifest v1 remains valid and digest-stable; manifest v2 accepts only the generic runtime;
- arbitrary workflow names, unknown runtime versions, extra fields, bad identities, unreviewed
  tools, and invalid limits are rejected;
- snapshot creation resolves and copies the model target, reviewed tool schemas, grants, and
  every execution limit exactly once;
- snapshot mutation/deletion is rejected and failed writes leave original content intact;
- generic workflow determinism and replay across worker-code revisions;
- no-tool, one-tool, ordered multi-tool, denial, malformed arguments, oversized arguments,
  oversized results, iteration exhaustion, retry, cancellation, and atomic completion;
- activity retries create one audit request, at most one effective read-only execution under
  the existing idempotency contract, one result event, and one assistant message;
- changing current defaults, model aliases, manifests, or grants cannot affect an accepted run;
- unsupported/missing/mismatched snapshots fail closed without model or MCP calls;
- owner isolation remains enforced for turns, events, cancellation, snapshots, and tool audit
  identifiers;
- legacy history fixtures remain replayable in isolated tests but are absent from production
  worker registration;
- repository and Compose checks prove the retired queue and workflows are not reintroduced.

### Live acceptance

1. Start two declarative agent versions concurrently; require both to execute through
   `AgentRunWorkflow` on the generic queue with distinct pinned snapshots.
2. Run the existing time-tool restart smoke against `1.1.0`; restart the generic worker after
   persisted authorization and require one execution, one completed audit row, ordered events,
   and one final message.
3. While a generic `1.1.0` run is active, publish or activate a distinct newer default; require
   the active run to finish with the original snapshot digest, instructions, model, grants, and
   limits.
4. Start runs pinned to both generic versions after the default changes and prove their
   workflow metadata, snapshots, audits, and traces remain version-distinct.
5. Stop and restart the generic worker during accepted work; require recovery on the same
   workflow ID and snapshot without a legacy poller or fallback route.
6. Repeat fabricated, diagnostic, name-confused, malformed, and prompt-policy-override calls;
   require durable denial and no unauthorized MCP execution.
7. Repeat cross-user list/read/stream/cancel/retry and identifier-isolation checks.
8. Pass the complete Phase 4 and Agentgateway migration gates with trace lookup by turn
   correlation ID.

The smoke should use deterministic adapter tests for most matrix cases and reserve paid model
calls for the minimum concurrent-version, restart, pinning, and end-to-end tool proofs. Record
the expected and actual model-call count in the results.

## Operational rollout and rollback

Rollout order:

1. apply additive schema/seed changes without changing the default release;
2. deploy the generic worker on its new queue;
3. verify its poller and generic readiness;
4. deploy API snapshot/routing support;
5. execute a pinned `1.1.0` canary;
6. set `1.1.0` as the default for new conversations;
7. run the complete acceptance suite.

Rollback changes only new routing/default selection:

- close Agent admission by returning to maintenance mode;
- leave the generic worker running until all accepted generic histories finish;
- do not mutate snapshots, published versions, grants, workflow IDs, or artifacts;
- diagnose and resume accepted runs on the generic queue rather than starting replacements;
- restoring the retired worker requires the separate Increment 6.5 rollback procedure and is
  not a normal Increment 7 rollback.

Readiness/status output must show the generic worker, generic queue, poller health, admission
state, and currently resolved default release without exposing secrets.

## Definition of done

- `AgentRunWorkflow` contains no tool-assistant-specific prompt, model, tool list, or limit;
- generic releases execute solely from immutable, self-contained run snapshots;
- `tool-assistant:1.0.0` and its legacy histories remain intact as historical data;
- `tool-assistant:1.1.0` executes through the generic workflow on the new queue;
- two generic agent versions complete concurrently through the same workflow type;
- a generic active run survives worker restart and publication/default activation of a newer
  release without behavioral drift or duplicate side effects;
- policy denial, event replay, cancellation, atomic completion, owner isolation, and Langfuse
  correlation retain the accepted Phase 4 behavior;
- all automated, Compose, migration, Agentgateway, and live regression gates pass;
- the runbook documents rollout, inspection, recovery, and rollback, and results contain
  reproducible acceptance evidence.

## Expected changed surfaces

- `apps/portal-api/portal_api/agent.py`: add only the production generic workflow;
- `apps/portal-api/portal_api/worker.py`: register the generic workflow and activities;
- `apps/portal-api/portal_api/main.py`: build closed snapshots and route by runtime contract;
- `apps/portal-api/portal_api/catalog.py`: backward-compatible manifest-v1 plus manifest-v2
  validation;
- `apps/portal-api/portal_api/config.py`: generic task queue and admission readiness;
- `apps/portal-api/portal_api/models.py` and a new additive migration: snapshot immutability and
  the `1.1.0` publication/default where required;
- `agents/tool-assistant/1.1.0/manifest.json`: first generic declarative release;
- `compose.yaml`: the sole generic Agent worker service;
- backend tests, migration/Phase 4 verification, and new Increment 7 smoke/verification scripts;
- README, architecture transition status, runbook, and results after verification.
