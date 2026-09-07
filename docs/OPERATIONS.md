# Porfirium operations

Status: current pre-migration deployment

These procedures operate the existing Portal API and Temporal-based runtime. The target Agent
Registry, Agent Runner, SDK, and JetStream architecture has completed its contract foundation,
feasibility gates, infrastructure foundation, Registry, Checkpoint API, Runtime API, SDK, isolated
Runner MVP, configuration, delegation, gateway policy, durable conversations, and end-to-end
completion and human-input suspension phases, but is not yet the deployed runtime.
Target-service procedures will replace this document during an accepted transition.

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

Target-platform verification is independent of the deployed legacy runtime:

```bash
./scripts/contracts/verify.sh
./scripts/target-phase2/acceptance.sh
./scripts/target-phase3/acceptance.sh
./scripts/target-phase4/acceptance.sh
./scripts/target-phase5/acceptance.sh
./scripts/target-phase7/verify.sh
./scripts/target-phase8/verify.sh
./scripts/target-phase9/verify.sh
./scripts/target-phase10/verify.sh
./scripts/target-phase11/verify.sh
```

These gates require Docker with Compose and remove their isolated containers and volumes on exit.
Phase 3 builds temporary OCI fixtures. Phase 4 proves checkpoint restore in a second agent process.
Phase 5 starts PostgreSQL, JetStream, the Runtime API, and an unprivileged local-agent harness; it
restarts Runtime during an active message stream and verifies durable deduplication, completion
hashes, and lease fencing. Phase 7 verifies immutable configuration resolution, scoped delegation,
both MCP authorization dimensions, cancellation denial, and credential redaction. None of the
target acceptance harnesses use production credentials. Phase 8 verifies owner-scoped
conversations, idempotent message and Runtime-event handling, canonical completion persistence,
and presentation-sequence replay for SSE reconnects. Phase 9 verifies durable run admission,
message/checkpoint confirmation publication, order-independent completion convergence,
cancellation, interruption after visible output, and safe pre-output recovery.
Phase 10 verifies stable suspension identity, hidden partial saga state, commitment in either event
order, one effective owner-authorized response, exact attempt teardown, and checkpoint-bound resume.

Target Phase 7 requires `DELEGATION_SIGNING_SECRET` in addition to the target database and NATS
secrets. Supply it through deployment secret management. Never place that secret or an issued
delegated token in Compose files, logs, events, checkpoints, traces, or error responses.

The Conversation Service owns the `conversation` database and starts only after
`conversation-migrate` applies its ordered SQL migrations. It consumes Runtime message events with
durable JetStream consumers and publishes run intents from its transactional outbox. Treat
`presentation_events` and completed `messages` as authoritative reconnect and history state;
short-lived `message_chunks` may be expired only after canonical completion has committed. Never
renumber presentation sequences or reconstruct completed messages from retained deltas.

Phase 6 Runner checks are focused in the service and the accepted real-runtime isolation gate:

```bash
cd services/agent-runner
uv run ruff check .
uv run pytest -q
cd ../..
./scripts/feasibility/rootless-container-isolation/verify.sh
```

The Runner must execute as an unprivileged host service with access to its own rootless Podman
runtime. Do not expose that runtime socket, host mounts, infrastructure credentials, or caller-
controlled Podman flags to agent containers. Registry run-signing public keys and the Runtime API
capability secret must be supplied through the deployment secret mechanism, never committed.

For the target rootless topology, use `deploy/compose/rootless-host-runner.yaml` as an override and
scale the Compose `agent-runner` service to zero. The override publishes PostgreSQL, NATS, and Agent
Registry only on loopback, pins Runtime to `porfirium-agent-runtime-api`, and directs Portal BFF to
the host Runner through `host.containers.internal`. Start Runner as the same unprivileged user that
owns the rootless Podman control plane:

```bash
podman compose --profile target \
  -f deploy/compose/target.yaml \
  -f deploy/compose/rootless-host-runner.yaml \
  up -d --scale agent-runner=0

export DATABASE_URL='postgresql://agent_runner:...@127.0.0.1:15432/runner'
export NATS_URL='nats://127.0.0.1:14222'
export AGENT_REGISTRY_URL='http://127.0.0.1:18102'
export TARGET_RUNNER_BIND_HOST='<dedicated host interface reachable only from the Podman network>'
export TARGET_RUNNER_HOST="$TARGET_RUNNER_BIND_HOST"
# Also export the Runner NATS identity and deployment-managed signing values.
./scripts/target-runner/start-host.sh
```

The launcher refuses a non-rootless engine, a missing Runtime container, or incomplete Runner
configuration. It also rejects wildcard bind addresses: Runner must listen on a dedicated host
interface reachable from the rootless Podman network without exposing it to the LAN. It passes
`runtime:50051` to attempts and never mounts a Podman or Docker socket into an agent container.
Set `RUNNER_MAX_ATTEMPTS` to tune retries for attempts that exit before visible output; the default
is three. Retries also stop at the signed run deadline. Exhaustion records
`attempt_retry_exhausted`, removes the exact attempt container and network, and does not leave the
run scheduled indefinitely.

Publish the platform-owned model-only release from a trusted release host. Provide a Registry token
with the publisher role, a registered Ed25519 publication key, and the target OCI host. The script
builds and pushes the image, resolves the registry digest, renders the manifest into a temporary
directory, signs canonical provenance, and publishes the digest-pinned release. It never modifies
the immutable version directory.

```bash
export OCI_REGISTRY_HOST='registry.example'
export AGENT_REGISTRY_URL='https://registry-api.example'
export REGISTRY_PUBLISH_TOKEN='...'
export REGISTRY_PUBLICATION_KEY_ID='release-2026'
export REGISTRY_PUBLICATION_PRIVATE_KEY_FILE='/secure/release-2026.key'
export MODEL_ONLY_SET_DEFAULT=true
./scripts/target-model-only/publish.sh
```

Default selection additionally requires the Registry administrator role on the supplied token.
For the local development client, set `REGISTRY_PUBLISH_TOKEN=client_credentials`; the command then
obtains a short-lived token from `RUNNER_OIDC_TOKEN_URL` and does not persist it.

The checked-in local Keycloak configurator is for the disposable development realm only. It uses
the public demo administrator credentials already declared by the standalone Keycloak project,
creates or updates `porfirium-target-dev`, assigns the target service roles, adds the Registry
audience, and verifies a client-credentials token without printing it:

```bash
python3 scripts/target-keycloak/configure.py
```

Never point this helper at another Keycloak instance or copy its development secret into a shared
environment.

Before running the provider-backed smoke test, verify that the Agentgateway container can resolve
and connect to the configured provider over HTTPS. A sequence of Agentgateway `503` responses with
`Connect: deadline has elapsed` indicates host/container DNS or egress failure, not an admission,
OCI, isolation, or Runtime routing failure. Restore DNS/egress, then run:

```bash
python3 scripts/target-phase11/live_smoke.py
```

Runner consumes `porfirium.run.command.requested` and the completion handshake on durable
JetStream consumers. A container exit is diagnostic only and must never mark a run completed.
During incident recovery, inspect `run_completion`, `run_confirmations`, and `run_event_inbox`
before replaying an event. Replays are safe with the original event ID. Do not edit a terminal run:
the first valid terminal transition is authoritative.

For a run in `suspending`, redeliver its original suspension event; never fabricate a new
`suspension_id`. Runner retries removal of the persisted container and Conversation Service
reconciles the existing reservation. A `waiting_for_input` run has no active container. Resume only
through the committed input request so the new run retains the thread and starting checkpoint.

## Target-platform feasibility gates

Phase 1 feasibility probes are independent of the legacy verification suite. Run them when
changing the corresponding target-platform boundary. Each directory contains the accepted
behavior, prerequisites, and focused troubleshooting guidance.

```bash
./scripts/feasibility/rootless-container-isolation/verify.sh
./scripts/feasibility/langgraph-state-api/verify.sh
./scripts/feasibility/grpc-reconnect/verify.sh
./scripts/feasibility/jetstream-outbox-inbox/verify.sh
./scripts/feasibility/otel-langfuse/verify.sh
```

The isolation probe requires rootless Podman. The JetStream probe starts a temporary NATS
container through Podman. The LangGraph and gRPC probes create isolated Python virtual
environments under `/tmp`. Their first run may download pinned dependencies.

The OpenTelemetry probe requires Docker Compose and the local Langfuse dependencies. It starts a
temporary Collector, sends SDK and gateway spans through it, verifies one correlated trace in
Langfuse, and stops the Collector. Existing Langfuse dependency containers remain running.

The token-exchange probe targets standalone Keycloak 26.2.5 or newer. Configure its dedicated
realm clients once, using local administrator credentials without storing them in the repository,
then run the probe with its generated client secret:

```bash
python3 scripts/feasibility/keycloak-token-exchange/configure_and_probe.py \
  --base-url https://keycloak.local:8443 \
  --admin-user "$KEYCLOAK_ADMIN_USER" \
  --admin-password "$KEYCLOAK_ADMIN_PASSWORD"

KEYCLOAK_EXCHANGE_CLIENT_SECRET='<generated-secret>' \
  ./scripts/feasibility/keycloak-token-exchange/verify.sh
```

Use environment variables or an external secret manager for live values. Do not add generated
secrets, probe environments, or provider payloads to Git. The accepted evidence and limitations
for every gate are recorded in its `README.md` and summarized in the Phase 1 section of the
implementation plan.

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
