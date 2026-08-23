# Increment 7 — Generic versioned agent runtime results

Status: Implemented; deterministic and local runtime gates passed  
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

- backend Ruff and 33 Pytest tests;
- Python compilation and a single Alembic head at `0007_generic_runtime`;
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

One paid model/tool canary completed during incident recovery. The full worker-restart and
publication-drift acceptance scenarios remain operator-run checks when credentials and demo
users are intentionally placed in scope.

## Operation and rollback

Start with `./scripts/phase4/start.sh`. Inspect the worker with:

```bash
docker compose ps agent-worker portal-api
docker compose logs --tail=100 agent-worker portal-api
```

For routing rollback, set `AGENT_EXECUTION_MODE=maintenance` on the Portal API and leave the generic worker running until accepted histories finish. Do not alter published versions, grants, snapshots, completed data, or workflow IDs.
