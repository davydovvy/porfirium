# Increment 7 — Generic versioned agent runtime results

Status: Completed and accepted
Date: 2026-08-23

## Delivered

- one platform-owned `AgentRunWorkflow` and version-neutral activity set;
- the sole `porfirium-agent-runtime-v1` production queue and one `agent-worker` service;
- manifest schema v2 with declarative runtime contract version 1, while retaining schema-v1 validation;
- bundled immutable `tool-assistant:1.1.0`, copied reviewed grants, default selection, and transactional conversation upgrade;
- self-contained acceptance snapshots holding resolved model target, instructions, reviewed tool definitions, grants, and all limits;
- database triggers rejecting snapshot update and deletion;
- fail-closed binding, digest, runtime, schema, argument, result, iteration, and authorization validation;
- idempotent audit/result/final-message transitions and the existing stable workflow ID format.

The legacy `tool-assistant:1.0.0` catalog record and completed histories remain intact. No legacy workflow or queue is registered in production.

## Verification evidence

The following passed from the shared worktree:

- backend Ruff and 36 Pytest tests;
- Python compilation and a single Alembic head, subsequently advanced additively to `0008_versioned_tool_schema`;
- frontend ESLint, Vitest, TypeScript, and production Vite build;
- `docker compose config --quiet`;
- live additive migration from `0006_agent_immutable` to `0007_generic_runtime`;
- live Portal API readiness;
- live generic worker startup and registration on `porfirium-agent-runtime-v1`.

## First live run and recovery

The first user-submitted generic run exposed a Temporal Python payload-conversion defect before
the initial activity body executed. Activity inputs used `dict[str, object]`; Temporal cannot
materialize the abstract `object` value type and reported `Failed decoding arguments`. The
worker was healthy and polling the correct queue, but repeated decoding failures made the UI
appear to be waiting for a worker.

All Temporal-bound activity inputs now use JSON-compatible unparameterized dictionaries. A
regression test serializes and deserializes the initial execution-plan activity input through
Temporal's default payload converter. After rebuilding the worker, the failed execution was
restarted under the same workflow ID with its original immutable snapshot. It completed with
one authorized `demo_time-get_current_time` call, one completed audit/result sequence, and one
final assistant message. No snapshot or accepted turn data was rewritten.

One paid model/tool canary completed during incident recovery. The operator subsequently
reported the acceptance scripts passing and exercised the generic Agent through the portal.

## Acceptance follow-up: versioned MTG search correction

UI testing found that the original search contract required a free-text `query` even for a
structured `set_code` filter. Because query and structured filters were combined, set names and
codes returned no cards; an unfiltered short substring could instead match unrelated card text.
The bundled catalog always contained 20 records for each declared set.

Migration `0008_versioned_tool_schema` makes tool-catalog identities unique by stable name and
schema version, preserving all `1.1.0` grants and snapshots. It publishes
`tool-assistant:1.2.0` with search schema `1.1.0`, where query is optional, and makes that release
the default only for new conversations. Deterministic tests prove set-only RTR and M11 searches
return exactly their 20 in-set records and that the RTR code no longer matches unrelated text.

The user then exercised a new `tool-assistant:1.2.0` conversation in the portal, confirmed the
corrected progress, failure handling, bounded final synthesis, and RTR set search, and reported
that everything works. Increment 7 and Milestone M3 were accepted on 2026-08-23. Increment 8
remains unstarted.

## Operation and rollback

Start with `./scripts/phase4/start.sh`. Inspect the worker with:

```bash
docker compose ps agent-worker portal-api
docker compose logs --tail=100 agent-worker portal-api
```

For routing rollback, set `AGENT_EXECUTION_MODE=maintenance` on the Portal API and leave the generic worker running until accepted histories finish. Do not alter published versions, grants, snapshots, completed data, or workflow IDs.
