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
./scripts/target-phase12/verify-hardening.sh
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
The Phase 12 hardening gate verifies bounded delivery failure and dead-letter behavior, capacity
policy, orphan reconciliation, Runtime protocol compatibility, trusted builder policy, and the
additive Runner operator contract. It also covers owner-local retention boundaries and backup
script validation, signed run-trace propagation, cross-run identity rejection, and bounded
malformed-event handling. Run `./scripts/target-phase12/verify-recovery.sh` separately for the
disposable seven-database, JetStream, OCI, protected-key, and checksum restore exercise. This is
not the final Phase 12
two-agent acceptance gate.

Run the destructive, isolated lifecycle acceptance separately. It creates disposable Compose
resources, restarts Runtime during an active stream, proves a superseded open stream and reconnect
are fenced, and verifies idempotent cancellation performs one exact cleanup and emits one terminal
event:

```bash
./scripts/target-phase12/verify-lifecycle.sh
```

## Phase 12 live two-agent acceptance

Run the credentialed live gate only against an isolated target environment. Version 1.0.0 of
`model-only` and version 1.1.0 of `planning-assistant` must already be published and selected as
their default releases unless the optional publication flag is used.

```bash
export KEYCLOAK_TOKEN_URL=https://identity.example/realms/porfirium/protocol/openid-connect/token
export AGENT_REGISTRY_URL=https://registry.internal
export PORTAL_BFF_URL=https://portal.example
export RUNTIME_DATABASE_URL=postgresql://runtime_user:password@runtime-db/runtime
export OIDC_CLIENT_ID=portal-bff
export OIDC_CLIENT_SECRET=...
export TEST_USER_CLIENT_ID=porfirium-cli
export TEST_USERNAME=phase12-user
export TEST_PASSWORD=...
export TEST_OTHER_USERNAME=phase12-other-user
export TEST_OTHER_PASSWORD=...
./scripts/target-phase12/acceptance.sh
```

For a local workstation, keep these values in a mode-0600 `.env.phase12.local` file and load it
with `set -a; source .env.phase12.local; set +a`. The file is ignored by Git. Keep provider keys in
the ignored root `.env`; never copy either file into documentation, commits, or diagnostic output.

Before publication or any acceptance mutations, run the same command with
`PHASE12_PREFLIGHT_ONLY=true`. Preflight obtains both user tokens, requires distinct subjects,
performs the user-to-Registry token exchange, checks Registry and the complete Portal BFF dependency
graph for readiness, and verifies the Runtime database contains the Phase 12 tool-invocation table.
It does not publish images, change defaults, grant access, create conversations, or invoke a model:

```bash
PHASE12_PREFLIGHT_ONLY=true ./scripts/target-phase12/acceptance.sh
```

The gate grants that test user run access to both agents and completes one portal conversation with
each. It confirms that model-only has no Runtime tool records and planning-assistant has exactly one
successful result from `demo-time-mcp`. Set `AGENT_REGISTRY_AUDIENCE` when the deployment does not
use `agent-registry`. The second user must have a distinct subject; the gate proves that user's
conversation read and cancellation attempts return the same not-found boundary, and that malformed
portal input is rejected before reaching a service. Set `PHASE12_PUBLISH_AGENTS=true` only on a
trusted publication host with the
OCI and signing variables required by both publication scripts; publication pushes both images and
changes both default releases. `PHASE12_PUBLISH_AGENT` remains a deprecated alias for compatibility.
The normal gate does not publish or mutate release selection, though it does create access grants,
conversations, runs, messages, and audit records.

## Target retention

Run retention after a successful backup:

```bash
./scripts/target-phase12/run-retention.sh
```

The operation removes completed message chunks after 30 minutes, acknowledged transport outbox
rows only after the corresponding stream replay window, expired Runtime attempt buffers one day
after their deadline, old inbox deduplication records after their source stream expires, and
already-replayed encrypted dead letters after 31 days. It never deletes canonical messages,
presentation history, conversations, checkpoints, releases, run/attempt history, request
idempotency records, pending dead letters, or operator/security audit facts. In the rootless host
topology, run `python -m agent_runner.retention` from the stopped or quiescent host Runner
environment when prompted by the wrapper.

## Target backup and restore

Create a new protected backup directory only after freezing authoring and new conversations. In the
rootless topology, stop the host Runner and explicitly confirm that state:

```bash
export PORFIRIUM_BACKUP_KEYS_DIR=/secure/porfirium-recovery-keys
export PORFIRIUM_HOST_RUNNER_STOPPED=true
./scripts/target-phase12/backup.sh /secure/backups/porfirium-YYYYMMDDTHHMMSSZ
```

The command stops and later restarts running target writers, dumps every owning database, snapshots
JetStream and OCI registry volumes, archives the protected key bundle with mode `077`, and writes
SHA-256 checksums. The key bundle must include Registry publication/run-signing material and the
Runner capability and dead-letter encryption keys. Database, NATS, OIDC, gateway, and operator
credentials remain deployment-managed and must be recoverable separately.

Restore only into empty databases and empty JetStream/registry volumes. Verify `SHA256SUMS`, restore
the protected keys first, load each custom-format dump into its matching service-owned database,
unpack the two volume archives while their services are stopped, apply migrations, and start the
target stack. Before traffic is enabled, require readiness, Registry digest reconciliation, a
dead-letter inventory, Runner reconciliation, and the full target acceptance gate. Never restore
over a live or partially populated target deployment.

Target Phase 7 requires `DELEGATION_SIGNING_SECRET` in addition to the target database and NATS
secrets. Identity Delegation also receives `RUN_CAPABILITY_SECRET` so it can validate the exact
attempt-bound capability when Runtime exchanges a grant for an MCP token. Supply both through
deployment secret management. Runtime exchanges on every tool call and does not persist the token.
Never place either secret or an issued delegated token in Compose files, logs, events, checkpoints,
traces, or error responses.

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
Registry only on loopback, pins Runtime to `porfirium-agent-runtime-api`, directs Portal BFF to the
host Runner, and routes both model and MCP traffic from Runtime through Agentgateway on the
rootless host bridge. Set `TARGET_HOST_BRIDGE` and `TARGET_RUNNER_HOST` when the bridge is not
`10.255.0.1`. Agentgateway must bind that same bridge address rather than loopback alone. Start
Runner as the same unprivileged user that owns the rootless Podman control plane:

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
the immutable version directory. The same controls apply to the independently packaged planning
assistant.

```bash
export OCI_REGISTRY_HOST='registry.example'
export AGENT_REGISTRY_URL='https://registry-api.example'
export REGISTRY_PUBLISH_TOKEN='...'
export REGISTRY_PUBLICATION_KEY_ID='release-2026'
export REGISTRY_PUBLICATION_PRIVATE_KEY_FILE='/secure/release-2026.key'
export MODEL_ONLY_SET_DEFAULT=true
./scripts/target-model-only/publish.sh
```

Publish the two-stage planning assistant with the same release identity and trust policy:

```bash
export PLANNING_ASSISTANT_SET_DEFAULT=true
./scripts/target-planning-assistant/publish.sh
```

This publishes version 1.1.0 by default. To republish the immutable model-only planning release
from its existing source package, explicitly set `PLANNING_ASSISTANT_VERSION=1.0.0`. Version 1.1.0
requires the `time_get_current_time` scope; Portal BFF derives that scope from the visible signed
release rather than accepting it from the browser.

Tool invocation IDs are durable Runtime records. If Runtime reports `tool_outcome_ambiguous`, do
not replay the call under a new ID: determine the downstream outcome and reconcile it according to
the tool's contract. Read-only calls may be intentionally retried only through an operator-reviewed
workflow; side-effecting calls require downstream idempotency evidence.

Setting a default is optional. Grant users access through the Registry before expecting the new
agent to appear in the portal selector. Verify both immutable package builds before publication:

```bash
./scripts/target-phase12/verify-agents.sh
```

Package verification also runs each built image with the Runner-equivalent security constraints
and checks numeric non-root identity, zero effective capabilities, no-new-privileges, seccomp,
read-only root storage, non-executable bounded temporary storage, and absence of Docker or Podman
sockets. This complements the Runner launch-policy tests; it does not replace the rootless-host
feasibility gate or deployment-specific network-policy validation.

On the supported rootless Podman host, run the Phase 12 network gate separately:

```bash
./scripts/target-phase12/verify-network-isolation.sh
```

It creates two disposable internal networks, attaches only a controlled Runtime endpoint to the
attempt network, and verifies denial of public internet, cloud metadata, the host, another attempt,
platform database and messaging endpoints, Registry and service endpoints, and runtime sockets.

Run the consolidated final gate only when the environment is prepared for both the destructive
restore exercise and credentialed provider-backed conversations:

```bash
PHASE12_INCLUDE_RECOVERY=true PHASE12_INCLUDE_LIVE=true \
  ./scripts/target-phase12/verify-acceptance.sh
```

Without both opt-ins, the command still runs the local hardening, package, lifecycle, and network
gates, but exits with status 2 and reports final acceptance as incomplete. The lifecycle portion
proves duplicate Runtime delivery returns the original durable event identity, persists no second
event, survives Runtime restart, resumes at the accepted sequence, and fences superseded leases.

In the portal, selecting an agent affects only the next conversation; existing conversations stay
pinned to their release. Stop waits for Runner acceptance, aborts the current SSE request, and then
reloads authoritative projections. If that refresh fails, the run is still no longer presented as
active and the portal displays the refresh error. Cancellation of visible partial output produces
an interrupted assistant message; a terminal Runner state is never rendered as an active run while
the interruption event is still converging.

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

Runtime retries a model request at most three times for transport failures, HTTP 408/429/5xx, and
responses without output text. Other 4xx responses and responses exceeding Runtime bounds fail
closed without retry. Runtime logs only the failure stage, exception class, and HTTP status; it
does not log prompts, model output, delegated tokens, or provider response bodies. If Phase 12
reports `attempt_retry_exhausted`, correlate the run identifier with these sanitized Runtime logs
and Agentgateway request status before retrying the live gate.

Runner consumes `porfirium.run.command.requested` and the completion handshake on durable
JetStream consumers. A container exit is diagnostic only and must never mark a run completed.
Set `RUNNER_CONSUMER_MAX_DELIVERIES`, `RUNNER_MAX_CONCURRENT_RUNS`, and
`RUNNER_MAX_CONCURRENT_RUNS_PER_USER` to positive bounded values. Messages that exhaust delivery
move to `porfirium.dlq.message`; the diagnostic contains identifiers and a stable error code, never
the exception message or original payload.

Configure deployment-managed `RUNNER_OPERATOR_TOKEN` and `RUNNER_DLQ_ENCRYPTION_KEY` secrets
before using dead-letter operations. The encryption key must be a URL-safe base64-encoded 32-byte
Fernet key and must be included in protected backup/restore procedures. List
failures with `GET /v1/operations/dead-letters`. Replay with
`POST /v1/operations/dead-letters/{id}:replay`, a bearer operator token, `X-Operator-ID`, and an
`Idempotency-Key`. Replay republishes the exact stored JSON with its original event identity and
records an immutable operator audit fact. Malformed non-JSON payloads cannot be replayed. Inspect
the owning service state and correct the cause before replaying; never edit the stored payload.

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
