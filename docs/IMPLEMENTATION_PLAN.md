# Porfirium target implementation plan

Status: active implementation sequence

This plan turns the accepted target architecture into independently verifiable increments. The
legacy Portal API and Temporal stack remain a reference implementation until final cutover. The
target stack is developed alongside it; intermediate phases do not need to provide a functional
end-to-end platform.

The architecture contracts remain authoritative. This document owns implementation order,
technology selections, phase gates, and cutover strategy.

## Initial technology selections

- Python 3.12, FastAPI, SQLAlchemy, and Alembic for platform HTTP services.
- `grpc.aio` for the Agent SDK to Runtime API channel.
- React and Vite for the portal.
- NATS JetStream with `nats-py` for durable asynchronous communication.
- One PostgreSQL server in local development, with a separate database and user for each owning
  service. Services never share writable tables or ORM models.
- A Distribution-compatible local OCI registry and externally built, signed images.
- Rootless Podman as the preferred first Runner backend, subject to the isolation feasibility gate.
- OpenTelemetry Collector exporting to Langfuse.
- Agentgateway retained behind Porfirium authorization contracts for initial LLM and MCP access.

Technology selected by a feasibility gate is not final until the gate passes. A failed gate must
produce a short decision record describing the replacement rather than weakening an architecture
invariant.

## Target repository layout

```text
apps/portal-web/
services/portal-bff/
services/conversation-service/
services/agent-registry/
services/agent-runner/
services/agent-runtime-api/
services/identity-delegation/
services/configuration-service/
services/checkpoint-api/
packages/contracts/
packages/agent-sdk-python/
deploy/{compose,nats,keycloak,postgres,otel,registry}/
agents/<agent-id>/<version>/
```

Each service owns its migrations, tests, image, dependency lock, and operational procedures.
Shared packages contain only versioned transport contracts and the Agent SDK.

## Phase 0 — Contract foundation

Define the dependency-root interfaces before implementing new services:

- v1 OpenAPI contracts for Registry, Runner, Conversation, Checkpoint, Configuration, and Identity
  Delegation services;
- the Runtime gRPC bidirectional protocol;
- canonical HTTP errors, idempotency, trace propagation, and identity conventions;
- JetStream envelope, event catalog, schemas, and workflow fixtures;
- deterministic generated contract indexes, Python and TypeScript event registries, and protobuf
  descriptors;
- a reviewed semantic compatibility baseline and one offline verification entry point.

Exit gate: `./scripts/contracts/verify.sh` passes, generation is clean, and an incompatible v1
change is rejected. This gate is complete in the current tree.

## Phase 1 — Feasibility gates

Build disposable, executable spikes for the six decisions that can invalidate downstream work:

1. Keycloak exchange, MCP audience restriction, scope narrowing, renewal, logout, and revocation
   (complete on Keycloak 26.2.5).
2. Rootless container filesystem, capability, syscall, network, resource, timeout, and exact cleanup
   controls (complete on rootless Podman 6.1.0 with `runc`).
3. LangGraph checkpoint serialization plus interrupt/resume through an HTTP State API boundary
   (complete on LangGraph 1.2.11).
4. gRPC reconnect, ordered acknowledgement, retransmission, and deduplication across Runtime API
   restart (complete on gRPC Python 1.83.1).
5. JetStream outbox/inbox handling of duplicate, delayed, poison, and replayed messages
   (complete on NATS Server 2.12.15 with nats-py 2.15.0).
6. SDK and gateway OTLP correlation in Langfuse without agent-held Langfuse credentials
   (complete on OpenTelemetry Python 1.44.0 and Collector 0.132.0).

Each spike gets a script under `scripts/feasibility/<gate>/`, bounded fixtures, documented actual
results, and an accepted or rejected decision. Dependent service work starts only after its gate
passes.

All six feasibility gates are complete in the current tree.

## Phase 2 — Target infrastructure and service skeletons

Add NATS streams and permissions, service-owned databases, the OCI registry, OTLP Collector, and
independently deployable service skeletons. Establish reusable outbox and inbox patterns without
sharing persistence abstractions. Compose uses separate `legacy` and `target` profiles.

Exit gate: every service starts independently; database and NATS ownership is enforced; a durable
test event survives publisher, consumer, and NATS restart.

Implementation status: the target infrastructure and eight independently buildable FastAPI
service skeletons are present. The topology provides service-owned PostgreSQL databases,
persistent JetStream stream bootstrap, a private OCI registry, and an OTLP collector.
`./scripts/target-phase2/verify.sh` validates this structure. NATS uses separate authenticated
identities with subject-level permissions. The Runner owns initial transactional outbox/inbox
tables, and `./scripts/target-phase2/verify-durability.sh` proves publication and deduplicated
consumption survive NATS and consumer restarts. Dependency-aware readiness and cross-database
connection denial are verified for every target service. `./scripts/target-phase2/acceptance.sh`
passes; this phase is complete in the current tree.

## Phase 3 — Agent Registry MVP

Implement immutable agent identities and releases, digest-pinned OCI references, manifest and
compatibility validation, access grants, publication/deprecation, and signed run-specification
resolution. Reuse behavior from the legacy publisher where it matches the new contract, but do not
carry forward database-stored executable artifact bytes.

Implementation status: complete. The Registry owns migrations, immutable releases, access grants,
lifecycle audit, OIDC-authorized HTTP operations, OCI/provenance verification, and immutable signed
run specifications. `./scripts/target-phase3/acceptance.sh` builds and pushes independent images
and proves the exit gate against disposable Distribution and PostgreSQL services.

Exit gate: two separately built agents can be published without rebuilding Registry, releases are
immutable, access-filtered discovery works, and resolution returns an authorized signed snapshot.

## Phase 4 — Checkpoint API and SDK core

Implement checkpoint put/get/list, namespace authorization, optimistic concurrency, serialization
versions, payload bounds, idempotency, and lease fencing. Build the SDK identity, deadline,
configuration, error, and LangGraph checkpointer surfaces plus a local harness.

Implementation status: complete. The Checkpoint API owns immutable per-thread checkpoint versions,
bounded opaque payloads, namespace-scoped signed run capabilities, idempotency records, and
monotonic attempt fencing. The Python SDK provides run context, deadlines, immutable configuration,
typed errors, the checkpoint client, and an asynchronous LangGraph adapter. The disposable
`./scripts/target-phase4/acceptance.sh` gate proves checkpoint/replay, conflict rejection,
cross-process restore and continuation, and stale-epoch rejection without agent database access.

Exit gate: a graph checkpoints, exits, and resumes in another process without receiving a database
credential; stale lease epochs and conflicting versions are rejected.

## Phase 5 — Runtime API and message SDK

Implement gRPC bootstrap, capability validation, ordered frames, acknowledgement, deduplication,
reconnect, heartbeat, cancellation, message streaming, bounds, backpressure, and the Runtime event
outbox. Exercise it first with a local agent process and fake downstream consumers.

Implementation status: complete. The Runtime API terminates the v1 bidirectional gRPC stream,
validates signed attempt capabilities, fences superseded lease epochs, durably accepts ordered and
idempotent frames, and publishes accepted message/run events through a transactional outbox. The
Python SDK provides bounded message streams, canonical completion hashes, acknowledgement-based
buffer release, and reconnect/retransmission. `./scripts/target-phase5/acceptance.sh` proves
continuation across a Runtime restart, unique durable events, final-content hash integrity, and
old-epoch rejection without exposing NATS credentials to the agent process.

Exit gate: Runtime restart does not duplicate accepted chunks, final hashes validate, old epochs
fail, and no NATS credential reaches the agent.

## Phase 6 — Runner MVP

Implement idempotent admission, Registry resolution, run and attempt persistence, monotonically
increasing leases, scheduling, one rootless container per attempt, capability issuance, deadlines,
cancellation, cleanup, and reconciliation. Begin with a fixed-response agent and do not silently
recover after visible output.

Implementation status: complete. The Runner admits Registry-resolved signed specifications
idempotently, persists one active attempt lease with a monotonically increasing epoch, issues
attempt-bound Runtime capabilities, and creates a new fixed-profile rootless Podman container for
each attempt. Deadlines, idempotent cancellation by the exact persisted container ID, failed-start
handling, and restart reconciliation are enforced without accepting caller-controlled container
settings. The focused Runner suite and the real rootless-container isolation probe cover signed
specification tampering, attempt capability binding, fail-closed sandbox arguments, elapsed-time
cleanup, and preservation of unrelated containers.

Exit gate: one admission creates one run, at most one attempt lease is active, cancellation removes
the exact container, and the complete isolation probe suite fails closed.

## Phase 7 — Configuration, delegation, and gateways

Implement immutable configuration revisions and deterministic resolution; delegation-grant
creation, exchange, renewal, expiry, and revocation; and run-aware LLM/MCP authorization around the
gateway implementation. MCP requires both delegated user scope and a pinned run tool grant.

Implementation status: complete. Configuration revisions are owner-scoped, immutable, bounded,
idempotent, schema-digest checked, and deterministically resolved with release/user/conversation
precedence. Delegation grants are durable, short-lived, revocable, scope-narrowing, and bound on
exchange and renewal to an active run attempt and lease epoch. Gateway policy independently checks
pinned model/tool grants, requires delegated user scope for MCP, rejects cancelled runs, and applies
recursive credential redaction. `./scripts/target-phase7/verify.sh` is the focused verification
entry point.

Exit gate: allowed model and tool calls succeed, either missing authorization dimension denies a
tool call, cancellation blocks new work, and token redaction tests cover every output channel.

## Phase 8 — Conversation Service

Implement conversations bound to one release and thread, durable messages, input requests and
responses, presentation sequencing, message/run-intent outbox transactions, Runtime event
projection, canonical completion validation, replay, and the SSE-oriented event API.

Implementation status: complete. Conversation state is owner-scoped and bound to an immutable
release/thread pair. User messages and input responses atomically create presentation events and
run-intent outbox records. Runtime events use an inbox transaction, allocate per-conversation
presentation order, validate bounded contiguous deltas and canonical completion hashes, and retain
canonical terminal content independently of delta retention. Replay-first SSE uses presentation
sequence IDs for gap-free reconnect. `./scripts/target-phase8/verify.sh` is the focused gate.

Exit gate: duplicate requests and events are harmless, completed messages survive delta expiry,
SSE reconnect has no gap, and user ownership is enforced server-side.

## Phase 9 — End-to-end completion

Connect admission and event consumers. Implement result proposal, message/checkpoint confirmations,
Runner-owned terminal transitions, completion reconciliation, interrupted output, cancellation, and
safe pre-output attempt recovery.

Implementation status: complete. Conversation run intents are admitted through a durable Runner
consumer. Runtime result proposals converge with transactionally published message and checkpoint
commit confirmations; Runner alone commits and publishes the run terminal outcome. Confirmation
delivery is idempotent and order-independent. Cancellation publishes one terminal outcome, missing
containers recover only before visible output, and visible partial messages are interrupted rather
than regenerated. `./scripts/target-phase9/verify.sh` is the focused verification entry point.

Exit gate: a message completes through a fresh isolated container; exit code alone cannot complete
a run; missing or reordered confirmations converge without rewriting terminal state.

## Phase 10 — Human-input suspension

Implement the stable suspension ID, checkpoint/input-request saga, commitment event, bounded
attempt exit, reconciliation, exactly one effective response, and a new run restoring the same
thread.

Implementation status: complete. The SDK derives stable checkpoint and input-request identities
from one suspension ID, persists the checkpoint before proposing input, commits the saga, and ends
the activation with a typed suspension. Conversation Service hides reservations until commitment,
repairs either event order, accepts one owner-authorized effective response, and emits a new run
intent pinned to the committed checkpoint and original thread. Runner fences the exact attempt,
removes its container, and records the durable `waiting_for_input` state.
`./scripts/target-phase10/verify.sh` is the focused gate.

Exit gate: no container waits for a person, crashes between saga writes are repaired, and duplicate
or unauthorized responses cannot create another effective run.

## Phase 11 — Portal BFF and web migration

Move browser operations behind a thin BFF that composes owning-service APIs and provides SSE replay
and live delivery. Remove Direct LLM mode and provide a platform-owned model-only agent. Adapt
catalog, new-conversation, cancellation, input, and authoring views to target contracts. Do not
surface legacy conversations in the migrated portal; users start new conversations against newly
published target agent releases.

Implementation status: complete. The BFF validates browser identity, exchanges browser tokens
for audience-restricted Registry tokens, forwards owner identity only to owning services, composes
new conversation/message/input/cancellation operations, and proxies replay-first conversation SSE.
The portal uses target release-bound conversations only and can recover an active stream after a
reload. Target publication accepts only independently built, digest-pinned images with signed
provenance and leaves validation and lifecycle ownership in Registry.

The immutable run-input surface is now implemented: Conversation includes the bounded trigger
snapshot in its durable intent, Runner persists and signs it into the attempt capability, Runtime
returns it after capability validation, and the SDK exposes a typed value. The Runtime-mediated
model-call interface is also present: an agent can request only a model alias
pinned in its signed run specification, Runtime applies request/response bounds, and only Runtime
knows the platform gateway topology. Runner now creates a rootless Podman internal network for each
attempt, attaches only the platform Runtime endpoint, records the exact network in durable Runner
state and on the container, and removes it during exact cleanup. Failed creation, cancellation,
suspension, and reconciliation also remove a recorded network when no container ID survived. The
executable feasibility gate confirms that public, metadata, host, foreign-attempt, and
container-runtime access remain denied. The deployment overlay now keeps Runner on the host under
the same unprivileged Podman owner, pins the Runtime container identity, exposes Runner dependencies
only on loopback, and routes BFF to a non-wildcard Podman bridge listener. The immutable model-only
1.0.0 package bootstraps its identity from the signed capability, requests only the `default` model
through Runtime, and streams bounded output without tools or credentials. Its trusted-host
publication command builds and pushes the image, resolves the registry digest, renders the manifest
outside the immutable version directory, signs canonical provenance, publishes idempotently, and
can select the resulting release as default. The target topology has been exercised through BFF
authentication, durable admission, exact-digest image pull, isolated attempt startup, Runtime model
mediation, and gateway routing. Provider-backed response completion still requires outbound DNS
and HTTPS access to the configured provider; a provider outage now terminates after at most three
attempts (or the earlier run deadline) with `attempt_retry_exhausted` and cleans up its container
and network.
`./scripts/target-phase11/verify.sh` is the focused verification entry point.

Exit gate: the browser reaches only the portal origin, internal credentials and topology remain
private, and two users cannot discover or operate each other's resources.

## Phase 12 — Hardening and acceptance

Extend the bounded attempt retry policy with dead-letter operations and safe replay, capacity
controls, Runner reconciliation, retention, malformed-input tests, protocol compatibility,
supply-chain enforcement, backup/restore exercises, and full trace correlation.

Implementation status: in progress. Runner consumers now stop after a deployment-bounded delivery
count, persist bounded dead-letter records, publish credential-free diagnostics, and expose an
operator-authenticated, idempotent replay path with durable audit. Scheduling enforces global and
per-user active-run ceilings. Reconciliation removes both missing recorded attempts and unknown
Porfirium-labeled containers/networks. Runtime accepts only the explicit current/adjacent-minor
protocol window, and Registry can require signed provenance from a deployment allowlist of builder
identities. Owner-local retention now removes only expired transport residue while preserving
canonical conversations, messages, checkpoints, runs, releases, idempotency state, and audit
facts. The backup workflow captures all seven service-owned databases, coherent JetStream and OCI
storage, and protected signing/encryption keys; a disposable restore exercise verifies database
and immutable-volume integrity across all seven service-owned databases, JetStream, OCI storage,
and protected keys, including checksum-based tamper detection. The signed run trace now propagates
through SDK frames, Runtime
events, checkpoint/message confirmations, and Runner terminal events. Runtime, Runner, and
Conversation reject oversized, structurally malformed, cross-run, or trace-mismatched events
before state changes. `./scripts/target-phase12/verify-hardening.sh` is the focused gate for the
completed hardening slices; it is not the final Phase 12 acceptance gate.

The independently packaged `planning-assistant` now has two immutable releases. Version 1.0.0
exercises two independently mediated model calls. Version 1.1.0 declares the read-only
`time_get_current_time` grant, invokes it through the delegated Runtime path, and grounds its model
response with the bounded result. Both have behavior tests, OCI builds, manifest validation, and a
digest-pinned signed publication command. Run
`./scripts/target-phase12/verify-agents.sh` to verify both independently packaged agents. This
closes the two-package build requirement, but not the final exit gate: the full two-agent live
acceptance matrix still needs to run against published releases.

The tool-invocation path is additive to Runtime protocol v1: the Python SDK sends bounded typed
arguments under a stable invocation ID, Runtime validates the tool against the signed run grant,
and typed results remain bounded. Runtime exchanges the opaque delegation grant for the exact
attempt and requested tool scope on every invocation, retains the resulting short-lived MCP token
only in memory for that call, and forwards both user and run authorization to Agentgateway.
Identity Delegation independently binds grant, release, run, attempt, lease epoch, and requested
scope. Portal BFF resolves the selected user-visible release and derives delegation scopes only
from its immutable manifest. Runtime durably reserves each `(run_id, invocation_id)` before the
external call, replays a completed bounded result, rejects request reuse with different arguments,
and reports `tool_outcome_ambiguous` without re-executing a call left in progress. Revoked grants
and cross-run capabilities are covered by fail-closed tests. An opt-in live gate now drives the
tool-enabled release through authenticated Portal BFF conversation APIs and verifies the durable
Runtime invocation record. It requires a deployed target topology and test credentials, so it is
kept separate from the hermetic hardening suite. It now exercises the complete two-agent matrix:
the model-only release must complete with no tool records, while the planning release must complete
with exactly one successful delegated time-tool record. The lifecycle gate separately proves
idempotent cancellation with exact attempt cleanup and one terminal event, plus both mid-stream and
reconnect fencing after a replacement lease activates. Running the credentialed matrix against
published releases remains an environment acceptance activity. The matrix also uses a distinct
second user to prove foreign conversation reads and cancellation are hidden, and submits malformed
portal input to confirm browser-boundary validation. Package verification executes every agent
image under the Runner-equivalent non-root, read-only, no-exec tmpfs, capability-dropped,
no-new-privileges resource profile and probes common container escape surfaces. The rootless
deployment-network gate attaches only Runtime to a fresh internal attempt network and verifies the
agent cannot reach public, metadata, host, foreign-attempt, platform-service, or runtime-socket
targets.

`./scripts/target-phase12/verify-acceptance.sh` is the consolidated exit gate. It always runs
hardening, immutable-package, lifecycle, and rootless-network verification. It refuses to declare
final acceptance unless the operator explicitly enables both destructive recovery verification and
the credentialed two-user live matrix. Runtime lifecycle acceptance deliberately replays an
identical accepted frame before restart and requires the same durable event identity, then restarts
Runtime and resumes from the durable sequence.

The credentialed matrix has a non-mutating preflight mode that verifies both distinct user
identities, Keycloak token exchange, Registry and Portal dependency readiness, Runtime database
connectivity, and the tool-invocation migration before publication, access grants, conversations,
or provider-backed calls begin.

Portal component acceptance covers selecting either visible default release when creating a
conversation and recovering immediately after cancellation. A successful Stop response now aborts
the stale event stream, clears local running state, and reloads the authoritative conversation and
list projections instead of waiting indefinitely for a later SSE event. Runner cancellation emits
one message interruption for visible partial output before its single terminal run event, and BFF
projections never expose a terminal Runner state as active while that event converges.

Exit gate: the acceptance baseline in `SPECIFICATION.md` passes with two independently packaged
agents, including restart, duplicate delivery, cancellation, authorization, malformed input, and
isolation tests.

## Phase 13 — Offline migration and cutover

Freeze legacy authoring and new conversations, drain active Temporal workflows, and back up all
legacy state. Rebuild the agents selected for continued use as new signed OCI releases and publish
them through the target Registry. Preserve Keycloak identities, but do not import legacy
conversations, messages, runs, checkpoints, or Temporal history. After cutover, every conversation
starts fresh against a target release.

Switch the BFF after identity, release, ownership, and digest reconciliation. Keep the frozen legacy
stack and Temporal state read-only during the rollback window only for operational rollback; it is
not exposed as history by the target portal. Rollback switches traffic to that frozen stack; it
does not reverse-sync target writes. Retire Temporal only after target acceptance and
backup/restore tests pass.
