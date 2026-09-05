# Porfirium platform specification

Status: target product and engineering contract

## Purpose

Porfirium runs independently developed LangGraph agents for authenticated users. The platform
provides discovery, isolated execution, durable conversations, human interaction, model and tool
access, checkpoints, and telemetry without giving agent code infrastructure credentials.
Every conversation selects an agent release. There is no separate Direct LLM execution mode; a
simple model-only experience is implemented as a platform-provided agent under the same contracts.

## Required products

### User portal

The portal lets users authenticate, browse only agents they can access, select an immutable agent
version, create conversations, send messages, answer agent input requests, observe live progress,
cancel runs, and reopen durable history. A backend-for-frontend protects all internal services.

### Conversation Service

The Conversation Service owns conversation history, partial and final messages, input requests and
responses, user visibility, and presentation ordering. It creates run-request intent through a
transactional outbox and does not start containers directly.

### Agent Registry

The registry stores agent metadata, immutable versions, digest-pinned OCI artifact locations,
configuration schemas, SDK compatibility, resource policy, model/tool requests, publication state,
and user/group access grants. It authorizes selection and produces a signed immutable run
specification. It does not execute agent code.

### Agent Runner

The runner accepts idempotent run and cancellation requests, resolves an authorized run
specification, and runs each attempt in one isolated container. It injects only platform-derived
configuration, a short-lived run capability, and a delegated user access token for MCP calls. It
enforces resource, filesystem, process, network, time, and cleanup policy and publishes lifecycle
events.

### Agent Runtime API

The Runtime API terminates the SDK's authenticated gRPC bidirectional channel. It validates the
active run and attempt, handles acknowledgement and deduplication, delivers control frames, and
converts accepted agent frames into durable platform events. Agents receive no NATS credentials.

### Porfirium Agent SDK

Every supported agent uses the SDK to:

- send user-visible messages and progress;
- request and receive correlated user responses;
- invoke models through the LLM Gateway;
- discover and invoke granted tools through the MCP Gateway;
- store and restore LangGraph checkpoints through the State API;
- observe cancellation and deadlines;
- emit structured logs, metrics, traces, and Langfuse telemetry.

Direct NATS, database, gateway, or Langfuse access from agent application code is unsupported.

### Event bus

NATS JetStream durably transports run commands, lifecycle events, conversation events, user input,
and audit events. Delivery is at-least-once. All messages use versioned schemas, stable IDs,
correlation/causation IDs, per-aggregate sequences, user/run context, and W3C trace context.

### State, identity, and telemetry services

The State API owns LangGraph checkpoints. Identity Delegation Service owns user-token exchange,
renewal, and revocation. Telemetry Collector receives OTLP and exports to Langfuse without exposing
Langfuse credentials to agents.

### Configuration Service

Configuration Service owns versioned user and conversation configuration values and secret
references. Registry owns schemas/defaults and Conversation Service pins the selected revision.

## Agent development contract

- Agents are Python applications built on LangGraph.
- Agent packages contain code, locked dependencies, graph entrypoint, manifest, and compatible SDK.
- Releases are immutable OCI images addressed by digest.
- Agents may use only SDK-mediated platform interactions.
- Graph state is checkpointed at resumable and human-input boundaries.
- Human-input suspension ends the current container attempt; a response creates a new run that
  restores the same thread.
- Agents must handle cancellation and respect platform deadlines.
- A release declares requested models, tools, configuration, and resources; platform policy grants
  an equal or narrower effective set.

## Functional requirements

1. A user cannot discover, select, start, inspect, answer, or cancel an agent run without access to
   its agent and conversation.
2. The same idempotency key cannot create more than one conversation or run.
3. An accepted run pins its release image digest, SDK protocol, effective configuration, grants,
   resource policy, user, and trace identity.
4. Publishing or deprecating a release cannot alter an accepted run or existing conversation.
5. A run can emit multiple progress and structured messages but exactly one terminal outcome.
6. A user-input request has a stable ID and accepts at most one effective response; duplicates are
   harmless and unauthorized responses are rejected.
7. Restarting the portal, runner, NATS consumer, or agent host does not lose acknowledged durable
   events or create a second run container for the same active lease.
8. Agent containers can reach only approved platform endpoints and cannot access the runtime socket,
   host filesystem, metadata endpoints, internal databases, or another run.
9. SDK model, tool, message, checkpoint, and telemetry operations propagate the run trace context.
10. Telemetry failure does not fail a run; authorization, gateway, or checkpoint failure is exposed
    as a bounded typed error.
11. One conversation normally owns one LangGraph thread and may contain many bounded runs. Each run
    has at most one active attempt and each attempt has one new container.
12. Streaming deltas are ordered, bounded, deduplicated, and short-lived. Only a validated
    completion with canonical content becomes the durable assistant message.
13. Attempt lease epochs fence stale containers at Runtime, State, LLM, and MCP APIs.
14. Human-input suspension uses an idempotent checkpoint/input-request saga and is not visible or
    resumable until both records are committed.
15. Runner alone owns run terminal state and requires the pinned message/checkpoint confirmations;
    a container exit code alone cannot declare completion.

## API and event compatibility

HTTP APIs are versioned under `/v1`. Event types end in a schema major version such as
`porfirium.run.started.v1`. Additive fields are allowed within a major version and consumers ignore
unknown fields. Removing or changing meaning requires a new major version and a migration window.

All mutating APIs accept an idempotency key. Errors use stable machine-readable codes, a safe user
message, correlation ID, and retryability indicator. Internal stack traces and credentials are
never returned.

## Data ownership

- Portal BFF: browser sessions and disposable composed-view caches.
- Conversation Service: authoritative conversations, messages, input requests, and presentation
  sequence.
- Configuration Service: user/conversation values and versioned secret references.
- Agent Registry: agents, releases, artifacts, grants, and publication audit.
- Agent Runner: run admission, leases, container lifecycle, and terminal status.
- Agent Runtime API: protocol frames and delivery state, but no product entity ownership.
- State API: LangGraph checkpoint data and checkpoint retention metadata.
- JetStream: durable transport, not the only system of record for business entities.
- Langfuse: observability backend, not product state.

Services do not write another service's tables. Cross-service views are composed through APIs and
events. Database migrations are owned and deployed with their service.

## Security requirements

- Browser access uses Keycloak Authorization Code with PKCE and same-origin TLS.
- Internal APIs require audience-scoped workload or delegated tokens.
- Agent capabilities are short-lived, revocable, and scoped to one run.
- The browser token is exchanged for a short-lived, down-scoped user token whose audience is the
  MCP Gateway. Raw browser access tokens and refresh tokens never enter agent containers.
- Asynchronous admission carries only a revocable, non-secret delegation grant ID. Minting a token
  also requires the authorized Identity Delegation Service and a matching active run.
- The SDK presents the delegated token to the MCP Gateway. The gateway authorizes the intersection
  of user scopes and pinned run grants and exchanges again for a downstream MCP audience when
  necessary.
- NATS uses TLS, authenticated accounts/users, least-privilege subject permissions, payload limits,
  quotas, and JetStream encryption/storage controls appropriate to the environment.
- Tool execution is deny-by-default and validated against the pinned run grants on every call.
- Agent-supplied prompts, messages, checkpoints, tool data, files, and telemetry are untrusted and
  bounded.
- Secrets never appear in manifests, images, events, checkpoints, logs, traces, or browser payloads.

## Operational requirements

- Components are independently buildable, deployable, health-checked, observable, and scalable.
- Contract and integration tests verify each API/event boundary.
- Runner capacity is bounded globally and per user, with explicit admission backpressure.
- Consumers have retry limits and dead-letter handling; operators can inspect and safely replay
  failed messages.
- Reconciliation repairs divergence among run state, leases, containers, and events.
- Backup and restore cover each owning database, JetStream durable state, OCI artifacts, and
  required encryption/signing keys.

## Acceptance baseline

The target architecture is accepted when two independently packaged LangGraph agents can be
published without rebuilding platform services, access can be granted to different users, and each
can complete a multi-step conversation with every attempt in its own constrained container using
SDK model, MCP, checkpoint, user-input, and Langfuse capabilities. Restart, duplicate delivery,
cancellation, unauthorized access, malformed messages, and container escape probes must produce
bounded outcomes without cross-user or cross-run effects.

The detailed boundaries are indexed by [Architecture](docs/ARCHITECTURE.md). The accepted decisions
and prerequisites for a future implementation plan are summarized in
[Implementation planning handoff](docs/architecture/IMPLEMENTATION_HANDOFF.md).
