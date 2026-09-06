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

Exit gate: allowed model and tool calls succeed, either missing authorization dimension denies a
tool call, cancellation blocks new work, and token redaction tests cover every output channel.

## Phase 8 — Conversation Service

Implement conversations bound to one release and thread, durable messages, input requests and
responses, presentation sequencing, message/run-intent outbox transactions, Runtime event
projection, canonical completion validation, replay, and the SSE-oriented event API.

Exit gate: duplicate requests and events are harmless, completed messages survive delta expiry,
SSE reconnect has no gap, and user ownership is enforced server-side.

## Phase 9 — End-to-end completion

Connect admission and event consumers. Implement result proposal, message/checkpoint confirmations,
Runner-owned terminal transitions, completion reconciliation, interrupted output, cancellation, and
safe pre-output attempt recovery.

Exit gate: a message completes through a fresh isolated container; exit code alone cannot complete
a run; missing or reordered confirmations converge without rewriting terminal state.

## Phase 10 — Human-input suspension

Implement the stable suspension ID, checkpoint/input-request saga, commitment event, bounded
attempt exit, reconciliation, exactly one effective response, and a new run restoring the same
thread.

Exit gate: no container waits for a person, crashes between saga writes are repaired, and duplicate
or unauthorized responses cannot create another effective run.

## Phase 11 — Portal BFF and web migration

Move browser operations behind a thin BFF that composes owning-service APIs and provides SSE replay
and live delivery. Remove Direct LLM mode and provide a platform-owned model-only agent. Adapt
catalog, conversation, cancellation, input, and authoring views to target contracts.

Exit gate: the browser reaches only the portal origin, internal credentials and topology remain
private, and two users cannot discover or operate each other's resources.

## Phase 12 — Hardening and acceptance

Add bounded retries, dead-letter operations and safe replay, capacity controls, Runner
reconciliation, retention, malformed-input tests, protocol compatibility, supply-chain enforcement,
backup/restore exercises, and full trace correlation.

Exit gate: the acceptance baseline in `SPECIFICATION.md` passes with two independently packaged
agents, including restart, duplicate delivery, cancellation, authorization, malformed input, and
isolation tests.

## Phase 13 — Offline migration and cutover

Freeze legacy authoring and new conversations, drain active Temporal workflows, and back up all
legacy state. Import Registry data first, rebuilding executable releases as signed OCI images.
Import users by Keycloak subject and migrate compatible conversations and completed messages.
Archive records that cannot satisfy target invariants; do not fabricate run specifications for
historical executions.

Switch the BFF after count, ownership, digest, and identifier reconciliation. Keep the frozen
legacy stack and Temporal state read-only during the rollback window. Rollback switches traffic to
that frozen stack; it does not reverse-sync target writes. Retire Temporal only after target
acceptance and backup/restore tests pass.
