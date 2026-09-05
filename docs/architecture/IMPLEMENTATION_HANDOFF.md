# Architecture handoff for implementation planning

Status: architecture decisions accepted; implementation sequencing established

This document records what is fixed, what remains an implementation choice, and what evidence the
implementation must preserve. The active sequencing and phase gates are maintained in
[Target implementation plan](../IMPLEMENTATION_PLAN.md).

## Accepted decisions

- The product is single-tenant and multi-user.
- Every user conversation selects an agent; there is no separate Direct LLM mode. A model-only
  experience is a platform-provided agent.
- Browser traffic terminates at Portal BFF; no internal service is browser-accessible.
- Conversation Service owns chat history, partial/final messages, input requests, and presentation
  ordering.
- Agent Registry owns immutable releases, OCI references, access grants, and signed run
  specifications.
- External CI initially builds, scans, signs, and pushes agent OCI images; Registry verifies them.
- Agent Runner owns run admission, attempt leases, isolated containers, cancellation, and run state.
- Agent Runtime API is the sole interactive bridge between agent containers and platform messaging.
- Agents are LangGraph applications and use Porfirium Agent SDK for all platform interactions.
- SDK-to-Runtime transport is gRPC bidirectional streaming.
- Browser streaming uses SSE; browser commands use authenticated HTTP.
- Platform asynchronous messaging uses NATS JetStream with at-least-once delivery.
- Agents receive no NATS, database, provider, OCI, container-runtime, or Langfuse credentials.
- Each conversation normally maps to one LangGraph thread and contains multiple bounded runs.
- Each run may have multiple safe recovery attempts, with at most one active container.
- Human input checkpoints and ends the container; the response creates a new run.
- Suspension uses a stable ID, idempotent checkpoint/input-request saga, and reconciliation.
- Runner is the sole run-terminal authority and uses message/checkpoint commit confirmations.
- Attempts use monotonically increasing lease epochs enforced by all SDK-facing services.
- State API owns LangGraph checkpoints and exposes a logical checkpointer through SDK.
- LLM calls use the run capability and LLM Gateway.
- MCP calls use both pinned run grants and a delegated user OAuth access token.
- The agent token is exchanged, short-lived, down-scoped, and MCP-Gateway-audience restricted; it
  is not the browser token, ID token, or refresh token.
- Asynchronous admission carries a durable non-secret delegation grant ID, never a bearer token.
- Configuration Service owns versioned user/conversation values and secret references; Registry
  owns schemas/defaults and Conversation Service selects a revision.
- Telemetry uses SDK OpenTelemetry instrumentation through a collector that exports to Langfuse.
- Streaming deltas are short-lived; Conversation Service stores one canonical completed message.
- Temporal is not part of the target runtime architecture.

## Architecture source set

- [System architecture](../ARCHITECTURE.md)
- [Platform specification](../../SPECIFICATION.md)
- [Runtime model](RUNTIME_MODEL.md)
- [Service contracts](SERVICE_CONTRACTS.md)
- [Messaging and streaming](MESSAGING.md)
- [Identity and security](IDENTITY_AND_SECURITY.md)
- [Agent configuration](CONFIGURATION.md)
- [Agent SDK contract](AGENT_SDK.md)
- [Glossary](GLOSSARY.md)

If documents conflict, the more focused contract governs its subject. Any discovered conflict must
be resolved in the architecture set before implementation relies on it.

## Inputs preserved by the implementation plan

The active plan and its phase deliverables must define:

- repository layout and extraction order for every target deployable;
- API/event schema package format and code-generation workflow;
- selected language/framework for each service;
- PostgreSQL boundaries and initial migration/cutover strategy;
- NATS deployment, stream configuration, consumers, outbox/inbox implementation, and operations;
- gRPC protocol definitions and SDK packaging/versioning;
- Keycloak token-exchange feasibility and realm/client configuration;
- delegation-grant storage, expiry, revocation, and session integration;
- configuration revision storage and validation workflow;
- OCI registry, CI signing/provenance, and local development workflow;
- rootless container backend and enforceable isolation profile;
- coexistence, data migration, cutover, rollback, and eventual Temporal retirement;
- tests and acceptance evidence for each independently deployable increment.

## Implementation choices intentionally left open

These choices do not change the accepted logical architecture and should be selected during
planning with small feasibility spikes where needed:

- Docker Engine rootless, Podman, or containerd as the first Runner backend;
- physical database instances versus separate schemas/users on one PostgreSQL server;
- concrete OCI registry and image-signing products;
- NATS retention values, storage sizing, and replica counts;
- service implementation frameworks beyond the Python Agent SDK requirement;
- deployment orchestrator after the local Docker Compose topology;
- exact SDK chunk timing and byte thresholds within architecture limits;
- SSE fan-out optimization and caching;
- sender-constrained delegated tokens where supported;
- automated platform-side source builds in a later capability.

## Required feasibility gates

Before committing to dependent implementation work, prove:

1. Keycloak can exchange the user grant for the required MCP audience/scopes and support renewal
   without exposing refresh tokens to the agent.
2. The selected runtime can enforce non-root, filesystem, capability, syscall, network, resource,
   timeout, and exact-container cleanup controls.
3. LangGraph checkpoint serialization and interrupt/resume work through the proposed State API
   boundary rather than direct database access.
4. gRPC bidirectional reconnect and frame deduplication preserve ordered SDK messages across a
   Runtime API restart.
5. JetStream outbox/inbox processing tolerates duplicate, delayed, poison, and replayed messages.
6. OpenTelemetry spans emitted by SDK and gateways correlate in Langfuse without agent-held
   Langfuse credentials.

## Planning invariants

No implementation increment may:

- create a second browser-facing internal service;
- give an agent infrastructure credentials or general network access;
- introduce shared writable databases or cross-service ORM imports;
- create an alternative run-admission path around Runner HTTP;
- let callers choose container security settings;
- treat JetStream delivery as exactly once;
- keep containers alive while waiting for human input;
- persist bearer tokens in specifications, events, checkpoints, logs, traces, or artifacts;
- accept operations from a superseded attempt lease epoch;
- expose arbitrary plaintext secrets to agent code in the initial architecture;
- make telemetry a prerequisite for successful product state changes;
- mutate an accepted release, run specification, completed message, or checkpoint version.

## Definition of architecture-ready

Architecture is ready for implementation planning when this source set has no broken references or
contradictory ownership claims and the team accepts the decisions above. Feasibility gates may be
scheduled as the first planning increments, but their success must precede any architecture that
depends on the selected technology.
