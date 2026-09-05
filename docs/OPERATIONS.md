# Porfirium operations

Status: current pre-migration deployment

These procedures operate the existing Portal API and Temporal-based runtime. The target Agent
Registry, Agent Runner, SDK, and JetStream architecture is documented but not yet implemented.
Future target-service procedures will replace this document during an accepted transition.

## Start

Ensure standalone Keycloak is running, `portal.local` resolves to `127.0.0.1`, and the uncommitted
`.env` contains the generated local secrets and Yandex configuration.

```bash
./scripts/phase4/start.sh
./scripts/phase4/status.sh
```

Open <https://portal.local:8444>. For local demo data, sign in as `alise` or `bob` with password
`123456`.

## Use and inspect

Create a conversation against a selected immutable agent release. The current pre-migration stack
executes turns with `AgentRunWorkflow` on `porfirium-agent-runtime-v1`.

Useful interfaces and logs:

```bash
docker compose logs --tail=100 agent-worker portal-api agentgateway \
  demo-time-mcp demo-mtg-catalog-mcp
```

- Temporal: <http://localhost:8080>
- Agentgateway: <http://localhost:8089>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

Workflow IDs use `porfirium-agent-<turn-id>`. A turn's correlation ID is propagated as its W3C
trace ID, allowing model and tool activity to be inspected together in Langfuse.

## Filesystem agent publication

Validate without database access:

```bash
cd apps/portal-api
.venv/bin/porfirium agents validate ../../agents/tool-assistant/1.3.0 --json
cd ../..
```

Perform platform validation, publication, and status inspection inside the Portal API container:

```bash
docker compose exec portal-api .venv/bin/porfirium agents validate \
  /agents/tool-assistant/1.3.0 --platform --json
docker compose exec portal-api .venv/bin/porfirium agents publish \
  /agents/tool-assistant/1.3.0 --json
docker compose exec portal-api .venv/bin/porfirium agents status tool-assistant:1.3.0 --json
```

An identical repeated publication is safe. Changed content under an existing semantic version is
rejected; publish a new version instead. Publication does not change the default. Removing a source
directory after publication does not affect stored releases, though repository packages should be
kept for reproducibility.

## Portal agent authoring

Assign `genai-agent-author` to users who create, revise, validate, and privately test their drafts.
Assign `genai-agent-publisher` separately to users who publish or deprecate releases. Restart the
user's Keycloak session after role changes.

Author workflow:

1. Create a structured declarative draft in **Agent builder**.
2. Save an immutable revision, using the displayed current revision for later updates.
3. Validate the exact revision and resolved model/tool configuration.
4. Run a bounded private test pinned to that revision and digest.
5. Revalidate and retest after any change.

A publisher reviews the exact revision, digest, validation, and successful test. Publication reruns
platform validation transactionally. Draft tests are owner-only, absent from ordinary catalogs,
and can make real provider/tool calls.

Deprecation removes a non-default release from new selection without changing accepted runs. The
current default cannot be deprecated until another default is selected through an explicit
supported operation.

## Verify

```bash
./scripts/phase4/verify.sh
./scripts/increment8/verify.sh
./scripts/increment9/verify.sh
```

These gates cover backend and MCP tests, Python lint, frontend lint/tests/build, Compose validation,
secret scanning, declarative runtime behavior, filesystem publication, and portal authoring.
Provider-backed smoke tests are intentionally separate because they use credentials, external
state, and paid APIs.

## Recovery

If an MCP service or Agentgateway is unhealthy, inspect and restart only that service. If the agent
worker is unavailable, restart it; accepted workflows resume from Temporal history.

```bash
docker compose restart agent-worker
docker compose logs --tail=200 agent-worker
```

`Failed decoding arguments` indicates an activity payload/contract mismatch, not a missing poller.
Fix and redeploy the worker. If retries are exhausted, confirm the application turn is non-terminal
and recover using the same workflow ID and original `run_snapshot_id`; never create a replacement
snapshot for an accepted turn.

## Rollback and stop

For a faulty agent version, stop selecting it or deprecate it when allowed, then create new
conversations against a known-good release. Let accepted work finish from its immutable snapshot.
Do not edit or delete releases, artifacts, grants, snapshots, conversations, audit rows, or
Temporal histories to roll back behavior.

To stop the runtime without deleting state:

```bash
./scripts/phase4/stop.sh
```

Do not run `docker compose down -v` unless permanent deletion of application, Temporal, and
observability state is explicitly intended.
