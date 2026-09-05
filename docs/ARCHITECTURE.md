# Porfirium target architecture

Status: authoritative target design

Porfirium is a multi-user platform for independently developed LangGraph agents. Each agent runs
in its own isolated container and uses the Porfirium Agent SDK for every platform interaction.
Components communicate through versioned APIs and durable NATS JetStream messages so they can be
developed, deployed, and scaled independently.

## Design principles

1. Each component owns one cohesive capability and its data.
2. Components integrate through documented, versioned contracts rather than shared Python modules
   or database tables.
3. The browser communicates only with the Portal BFF. Internal credentials and topology never
   reach browser code.
4. Agent code is untrusted. It receives a run capability and a delegated, audience-restricted user
   token, never the browser token, refresh token, or infrastructure credentials.
5. Commands and events are durable, idempotent, ordered within an aggregate, and safe to replay.
6. Agent releases and accepted runs are immutable and addressed by digest.
7. Control-plane availability is independent from an individual agent's health.
8. OpenTelemetry context and stable identifiers cross every HTTP and NATS boundary.

## System context

```text
Browser -> Portal Web/BFF -> Conversation Service
                    |              |
                    v              v
              Agent Registry   NATS JetStream
                    ^              ^
                    |              |
                Agent Runner -> Agent Runtime API
                    |              ^
                    v              |
             isolated attempt -> Agent SDK/LangGraph
                                      |  |  |  |
                                    LLM MCP State OTLP Collector -> Langfuse
                                     GW  GW  API
                                          ^
                                  delegated user OIDC

Portal BFF -> Identity Delegation Service -> Keycloak
Agent Runner -> OCI Registry
Agent Runner -> Configuration Service
```

Only the BFF is browser-facing. Conversation, Registry, Runner, Runtime, State, identity, gateway,
NATS, OCI, database, and observability services are private platform components.

## Component boundaries

### User portal

The user portal consists of a React UI and a thin backend-for-frontend API. It owns:

- authentication and browser sessions;
- agent discovery views filtered by the current user;
- conversation creation, history, and presentation projections;
- submission of run, cancel, and user-response commands;
- SSE or WebSocket delivery of user-visible events;
- authoring and administration screens that call owning services.

The portal does not resolve artifacts, start containers, execute agents, call models or tools on
an agent's behalf, or read another service's database. It builds its chat projection from durable
events and can rebuild that projection by replaying them.

### Conversation service

The Conversation Service owns conversations, user and assistant messages, streaming projections,
input requests/responses, user ownership, and presentation ordering. User-message persistence and
publication intent are one outbox transaction. It does not own run or container state.

### Agent registry

The Agent Registry is the source of truth for agent identity, releases, artifacts, and access. It
owns:

- agent metadata and immutable semantic versions;
- OCI image references pinned by digest and their provenance;
- SDK and runtime compatibility requirements;
- enabled models, tools, resource limits, and configuration schema;
- user, group, and role access grants;
- publication, deprecation, and default-selection policy;
- resolution of an immutable run specification.

The registry stores metadata in its own PostgreSQL schema/database. Agent source and built images
live in an artifact store and OCI registry; they are never stored in the portal or runner image.
No component joins registry tables directly. The runner receives a signed, immutable run
specification containing everything needed to start one run.

Minimum API surface:

```text
GET  /v1/agents                         list agents visible to the caller
GET  /v1/agents/{id}/versions/{version} get visible release metadata
POST /v1/releases                       publish an immutable release
POST /v1/releases/{id}:deprecate        block new selection
POST /v1/run-specifications:resolve     authorize and pin a release for a run
```

### Agent runner

The Agent Runner owns container lifecycle and run admission. It exposes an internal API and
consumes durable run commands. It owns:

- validating signed run specifications and rejecting mutable image tags;
- creating exactly one isolated container for a run ID;
- injecting non-secret configuration, a short-lived run capability, and a delegated user token;
- enforcing CPU, memory, PID, disk, time, filesystem, capability, and network limits;
- monitoring health, heartbeats, exit status, cancellation, and cleanup;
- publishing canonical lifecycle events;
- reconciling containers and JetStream state after restart.

Run containers are non-root, read-only, capability-dropped, resource-bounded, and have no Docker
socket, host mount, cloud metadata access, or infrastructure credentials. Their network can reach
only explicitly allowed platform APIs. Containers are not reused between runs, users, or agent
versions.

The Portal BFF never supplies an image or security profile. It submits a run request containing an
authorized agent selection. The runner obtains the immutable specification from the registry and
derives the complete sandbox profile from platform policy.

Minimum internal API surface:

```text
POST /v1/runs             accept an idempotent run request
GET  /v1/runs/{run_id}    return lifecycle state
POST /v1/runs/{run_id}:cancel
GET  /health/live
GET  /health/ready
```

The HTTP API acknowledges admission; run progress and agent interaction use JetStream.

### Agent Runtime API

Agent Runtime API owns the gRPC bidirectional channel used by the SDK. It validates the active run
capability and attempt lease, acknowledges and deduplicates frames, accepts messages and progress,
delivers cancellation and control data, and publishes accepted events through an outbox. Agent
containers receive no NATS credentials.

### Configuration Service

Configuration Service owns user and conversation configuration values plus versioned secret
references. Registry owns the release schema and defaults; Conversation Service owns which
configuration revision a conversation selects. Run admission validates and pins their effective
combination. Arbitrary secret values are not delivered to agent code in the initial architecture.

### Porfirium Agent SDK

The Python SDK is the only supported integration layer for agent application code. Agents use
LangGraph for graph definition and execution, but application code does not call platform
databases, NATS subjects, gateways, or Langfuse wire APIs directly.

The SDK provides:

- `messages.send(...)` to publish assistant, status, progress, and structured UI messages;
- `messages.request_input(...)` to suspend for and receive correlated user input;
- `llm.invoke(...)` and streaming variants through the LLM gateway;
- `tools.list()` and `tools.invoke(...)` through the MCP gateway using run-scoped grants;
- `checkpoints.get/put/list(...)` for LangGraph-compatible durable checkpoints;
- cancellation, deadlines, run identity, and configuration access;
- structured logs, metrics, traces, and Langfuse spans with propagated context;
- idempotency helpers and typed error normalization.

For MCP calls, the SDK sends the run's delegated user access token to the MCP Gateway. The token
represents the user, has the MCP Gateway as its audience, contains only approved scopes, and has a
short lifetime bounded by the run. The MCP Gateway validates it and, when a downstream MCP server
has a distinct audience, exchanges it for an equally or more narrowly scoped token for that server.

The SDK owns protocol details, retries, timeouts, telemetry propagation, payload limits, and
redaction defaults. It must not hide authorization failures or retry non-idempotent operations
without an idempotency key. SDK compatibility is declared by the agent release and checked before
admission.

### Event bus

NATS with JetStream is the durable communication backbone. Core NATS may be used only for
discardable signals such as live presence; commands, agent messages, user responses, and lifecycle
events use JetStream.

Initial streams:

| Stream | Subjects | Purpose | Retention |
|---|---|---|---|
| `RUN_COMMANDS` | `porfirium.run.command.*` | start, cancel, pause, resume | work queue |
| `RUN_EVENTS` | `porfirium.run.event.*` | lifecycle, progress, failures | limits/age policy |
| `CONVERSATION_EVENTS` | `porfirium.conversation.event.*` | durable messages | durable interest |
| `MESSAGE_DELTAS` | `porfirium.message.delta.*` | partial response chunks | short retention |
| `USER_INPUT` | `porfirium.input.command.*` | correlated user responses | work queue |
| `AUDIT_EVENTS` | `porfirium.audit.event.*` | security-relevant facts | long retention |

All messages use the canonical versioned envelope defined in
[Messaging and streaming](architecture/MESSAGING.md#event-envelope).

Delivery is at-least-once. Consumers use durable names, explicit acknowledgements, bounded retry,
dead-letter handling, and inbox/idempotency records. Producers use an outbox when a database write
and event publication form one business operation. Ordering is guaranteed only per run or
conversation aggregate, never globally. Schemas are additive within a major version and validated
at every boundary.

### Platform gateways and state API

The LLM Gateway owns provider routing, quotas, credentials, request normalization, and model
telemetry. The MCP Gateway owns tool discovery, delegated-user authorization, downstream token
exchange, and transport. A platform policy layer resolves the run's exact model and tool grants
before issuing scoped capabilities; gateways enforce those grants again on every call.

The State API owns checkpoint persistence. It exposes a LangGraph-compatible logical checkpointer
through the SDK while enforcing user, agent, thread, run, namespace, size, version, and retention
constraints. Agent containers never receive a database URL. Checkpoints are distinct from portal
chat projections and JetStream retention.

An identity delegation service creates a durable opaque delegation grant from the portal-held user
session, then exchanges that grant for a short-lived token whose audience is the MCP Gateway and
whose scopes are the intersection of the user's rights, agent release request, and platform policy.
Only the grant ID crosses asynchronous admission boundaries. The original access token and every
refresh token stay in the BFF/delegation boundary and are never persisted in a run specification,
event, checkpoint, log, trace, or agent filesystem. Long-running agents request renewal through the
SDK; renewal is allowed only while the user grant and run remain active.

The SDK and services emit OTLP to a platform Telemetry Collector, which exports to Langfuse.
Telemetry export is asynchronous and bounded; failure must not fail or mutate the run. Agents
receive no Langfuse credential. OpenTelemetry is the propagation standard and Langfuse remains a
replaceable backend rather than a dependency embedded in business contracts.

## Agent package contract

An agent release is built into an immutable OCI image. The image contains application code,
LangGraph graphs, locked dependencies, and a compatible Porfirium SDK. A manifest declares:

```yaml
apiVersion: porfirium.ai/v1
kind: Agent
metadata:
  name: example-agent
  version: 1.0.0
spec:
  image: registry.local/example-agent@sha256:...
  entrypoint: example_agent.main:graph
  sdk: ">=1.0,<2.0"
  models: [default]
  tools: [time.current]
  configSchema: {}
  resources:
    cpu: "500m"
    memory: "256Mi"
    timeoutSeconds: 300
```

Publication validates the manifest, digest, provenance, dependency policy, SDK compatibility, and
requested capabilities. A run specification pins the release, image digest, effective grants,
configuration, resource policy, SDK protocol, and trace identity. Mutable tags are never executed.

## Run and interaction flow

1. The browser asks the Portal BFF to store a message in a conversation with an accessible release.
2. Identity Delegation Service creates or validates a revocable, non-secret delegation grant.
3. Conversation Service stores the message, delegation grant ID, and run-request outbox atomically.
4. The admission consumer calls Runner HTTP with the original idempotency, user context, and grant.
5. Registry authorizes access and returns a signed immutable run specification.
6. Runner stores the run and scheduling outbox record atomically.
7. Identity service exchanges the grant for the MCP-audience delegated token.
8. Runner starts one isolated attempt with its run capability and delegated user token.
9. The LangGraph agent restores its thread checkpoint and executes through SDK.
10. SDK streams coalesced deltas through Runtime API; Conversation Service projects them and
   BFF streams them to the browser over SSE.
11. Completion, failure, timeout, or cancellation produces one terminal run event and removes the
    exact container.
12. At human input, SDK commits the suspension protocol, then the container exits. The
    authorized response creates a new run that restores the same thread in a new container.

## Identity delegation and security

- Keycloak authenticates users; services validate audience-specific tokens.
- Service-to-service identity uses short-lived workload credentials and explicit audiences.
- The BFF derives user identity from the token, never message payload claims alone.
- The browser access token is exchanged, not copied, before an agent receives delegated identity.
- The delegated token is audience-restricted to the MCP Gateway, down-scoped, short-lived, held only
  in container memory or a protected tmpfs file, and redacted from every output channel.
- The MCP Gateway checks both delegated user scopes and the immutable run's tool grants. Both must
  authorize the call.
- MCP servers with their own resource audience receive a further exchanged token, not the portal or
  agent-facing token.
- NATS accounts, subject permissions, and scoped credentials prevent agents from subscribing or
  publishing outside their run subjects.
- Agent capabilities expire, are revocable, and are bound to run, release, user, model, tools,
  checkpoint namespace, byte limits, and call limits.
- Each service owns authorization for its resources; UI visibility is not authorization.
- Secrets are referenced by name and resolved at runtime only for the component that needs them.
- Logs, events, checkpoints, traces, and errors are bounded and redacted before persistence.

## Reliability rules

- APIs require idempotency keys for create/start/cancel operations.
- Every consumer tolerates duplicate and delayed messages.
- Poison messages move to a dead-letter subject with bounded diagnostic metadata.
- Runner reconciliation compares admitted runs, live containers, leases, and terminal events.
- JetStream retention is not the sole business record; service-owned databases store required
  projections and immutable audit facts.
- Backpressure limits global and per-user concurrent runs and message rates before exhaustion.
- Readiness checks include required dependencies; liveness checks do not.
- Deployments support rolling SDK protocol compatibility across at least one adjacent major/minor
  migration window defined by the compatibility policy.

## Ownership and dependency rules

Services may share generated contract packages and the Agent SDK, but not ORM models, repository
classes, migration chains, or writable databases. An API owner publishes its OpenAPI or event
schema and contract tests. Downstream consumers test against those artifacts rather than importing
the service implementation.

The target deployables are:

```text
apps/portal-web
services/portal-bff
services/conversation-service
services/agent-registry
services/agent-runner
services/agent-runtime-api
services/identity-delegation
services/configuration-service
services/checkpoint-api
services/telemetry-collector
packages/agent-sdk-python
packages/contracts
agents/<agent-id>/
```

Agentgateway may continue as the LLM/MCP gateway implementation provided it satisfies the platform
contracts. NATS and JetStream replace Temporal as the target execution backbone; LangGraph and the
checkpoint API own agent workflow durability.

## Detailed contracts

- [Runtime model](architecture/RUNTIME_MODEL.md)
- [Service boundaries](architecture/SERVICE_CONTRACTS.md)
- [Messaging and streaming](architecture/MESSAGING.md)
- [Identity and security](architecture/IDENTITY_AND_SECURITY.md)
- [Agent configuration](architecture/CONFIGURATION.md)
- [Agent SDK](architecture/AGENT_SDK.md)
- [Implementation-planning handoff](architecture/IMPLEMENTATION_HANDOFF.md)
