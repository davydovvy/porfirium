# Service boundaries and contracts

Status: accepted architecture contract

Each service owns its API, database migrations, invariants, and emitted events. Services may share
generated schemas and SDK packages, but never ORM models, repositories, writable databases, or
implementation modules.

## Portal Web

Owns browser presentation only. It authenticates through the Portal BFF, renders agent discovery,
conversations, streaming messages, input requests, and run controls. It calls no internal service
directly and holds no platform or MCP credential.

## Portal BFF

Owns browser sessions, CSRF protection, same-origin APIs, and composition of user-facing service
responses. It validates Keycloak identity and delegates resource authorization to the owning
service. It exposes SSE for server-to-browser updates and HTTP commands for user actions.

It does not own agent releases, start containers, write checkpoints, or call tools for agents.

## Conversation Service

Owns:

- conversations and their selected release identity;
- user, assistant, progress, and structured UI messages;
- partial-message projections and final content;
- input requests and their single effective response;
- per-conversation presentation sequence numbers;
- user ownership and visibility policy.

Minimum API:

```text
POST /v1/conversations
GET  /v1/conversations
GET  /v1/conversations/{conversation_id}
POST /v1/conversations/{conversation_id}/messages
GET  /v1/conversations/{conversation_id}/events
POST /v1/input-requests/{request_id}/response
```

User message persistence and its outbox record are one database transaction. Run creation happens
asynchronously from that outbox event, avoiding a distributed transaction with the Runner.

## Agent Registry

Owns:

- agent identities, metadata, immutable releases, and deprecation;
- digest-pinned OCI artifact references, signatures, and provenance;
- SDK/runtime compatibility and agent configuration schemas;
- requested models, tools, and resource policy;
- user/group/role access grants;
- authorized, signed, immutable run specification resolution.

Minimum API:

```text
GET  /v1/agents
GET  /v1/agents/{agent_id}/versions/{version}
POST /v1/releases
POST /v1/releases/{release_id}:deprecate
POST /v1/run-specifications:resolve
```

The Registry does not build source or run images. Initially, external CI builds, scans, signs, and
pushes the OCI image. The Registry verifies digest, signature, provenance, policy, and compatibility
before publication.

## Agent Runner

Owns run admission, attempt leases, container lifecycle, sandbox enforcement, cancellation,
reconciliation, and run terminal state.

Minimum internal API:

```text
POST /v1/runs
GET  /v1/runs/{run_id}
POST /v1/runs/{run_id}:cancel
GET  /health/live
GET  /health/ready
```

The Runner's HTTP API is the only external run-admission path. It atomically stores an accepted run
and outbox command; an internal durable consumer schedules it. Callers cannot publish start commands
directly or provide image, mount, network, privilege, or runtime settings.

## Agent Runtime API

Owns the authenticated bidirectional channel between an untrusted agent container and platform
services. It:

- validates the run capability, active attempt lease, and fencing epoch;
- acknowledges and deduplicates agent frames;
- accepts messages, progress, input requests, heartbeats, and completion intent;
- delivers input, cancellation, deadlines, and capability-renewal results;
- enforces payload, rate, ordering, and protocol limits;
- converts accepted frames into outbox-backed platform events.

The initial transport is gRPC bidirectional streaming. Agent containers receive no NATS
credentials. The Runtime API is not the owner of conversations, runs, or checkpoints.

## Identity Delegation Service

Owns exchange, renewal, and revocation of user-delegated MCP tokens. It accepts a validated user
session and creates a durable, revocable, non-secret delegation grant ID. At attempt start it
validates that grant and mints or exchanges a token restricted to the MCP Gateway audience and
approved scopes. Only the grant ID crosses Conversation Service outbox and run-admission messages.

It never returns a browser refresh token to the Runner or agent. Renewal requires an active user
grant, active run, valid release policy, and unexpired server-side session authorization.

## Configuration Service

Owns versioned user/conversation configuration values and opaque secret references. Registry owns
schemas and defaults; Conversation Service owns the selected revision. Configuration Service
resolves and validates the effective configuration during admission without exposing plaintext
secrets. See [Agent configuration](CONFIGURATION.md).

## State API

Owns LangGraph checkpoint persistence, namespaces, optimistic concurrency, retention, and recovery.
It exposes a logical checkpointer through the SDK and scopes every operation to user, agent,
conversation thread, and run capability.

Minimum SDK-facing API:

```text
GET  /v1/threads/{thread_id}/checkpoints/{checkpoint_id}
GET  /v1/threads/{thread_id}/checkpoints
PUT  /v1/threads/{thread_id}/checkpoints/{checkpoint_id}
```

Checkpoint payloads are versioned, bounded, encrypted at rest where required, and treated as
untrusted data. Agents receive no database URL.

## LLM Gateway

Owns provider credentials, model aliases, request normalization, quotas, token limits, streaming,
and model telemetry. The SDK authenticates with the run capability. The Gateway enforces the pinned
model grant independently of agent input.

## MCP Gateway

Owns tool discovery, transport, delegated-user validation, per-tool authorization, downstream token
exchange, result bounds, and tool audit events. A call succeeds only when both the delegated user's
scope and the pinned run tool grant authorize it.

## Telemetry Collector

Receives OTLP telemetry from the SDK and services, applies redaction and limits, and exports to
Langfuse. Agents never receive Langfuse credentials. Telemetry failure cannot change run state.

## Infrastructure services

- NATS JetStream provides durable inter-service messaging.
- PostgreSQL instances or schemas store service-owned state without cross-service writes.
- The OCI registry stores immutable agent images.
- Keycloak authenticates users and supports delegated access-token exchange.
- Langfuse is an observability backend, not product state.

## User-message workflow

1. BFF authenticates the request and calls Conversation Service with an idempotency key.
2. Conversation Service stores the message and outbox event atomically.
3. A run-admission consumer calls Runner HTTP with the user, conversation, thread, release,
   delegation grant, configuration revision, and triggering input identifiers.
4. Runner asks Registry to authorize and resolve the immutable run specification.
5. Runner stores the accepted run and scheduling outbox record atomically.
6. Runner's scheduler starts one attempt and container.
7. Runtime, checkpoint, gateway, and conversation events drive the run to suspension or terminal
   state without shared database writes.

## Suspension workflow

SDK reserves a `suspension_id`, writes an idempotent checkpoint, creates an idempotent input
request, and publishes suspension commitment after both acknowledgements. A reconciler repairs
partial saga state. Runner removes the container only after committed suspension or bounded
failure cleanup.

## Completion workflow

Agent proposes a result through Runtime API. Conversation Service and State API emit required commit
confirmations. Runner is the sole run-terminal authority and completes only after receiving the
confirmations selected by the pinned run contract. Missing or duplicate events are reconciled
without guessing or rewriting an existing terminal state.

## Dependency rule

A synchronous dependency is allowed only when the caller requires an immediate authoritative
answer. State changes that can tolerate asynchronous completion use commands/events. Dependency
failure must have a bounded timeout, stable error, and documented effect on the owning entity.
