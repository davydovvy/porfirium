# Porfirium architecture

This document describes the current system. It intentionally excludes migration history and
completed delivery-stage records.

## Components

```text
Browser
  -> Caddy / portal.local
     -> React portal
     -> FastAPI Portal API
        -> application PostgreSQL
        -> Agentgateway -> Yandex model API
                         -> reviewed MCP services
        -> Temporal -> generic agent worker
        -> Langfuse
```

The FastAPI Portal API is the browser-facing security boundary. It authenticates users, enforces
ownership and roles, persists product state, admits turns, publishes agents, and streams events.

Agentgateway is the sole gateway for model and MCP traffic. Vendor-specific requests and responses
are normalized behind application-owned `ModelGateway` and `ToolGateway` adapters. The application
retains authority for tool policy and never delegates unrestricted tool execution to the gateway.

Temporal provides durable orchestration. `AgentRunWorkflow` runs immutable declarative snapshots
on `porfirium-agent-runtime-v1`; activities perform all I/O. PostgreSQL, not Temporal history or
Langfuse, is the product system of record.

## Conversation and execution flow

Direct mode accepts a user message, stores it, streams one Agentgateway model response, and stores
the terminal assistant message.

Agent mode resolves the explicitly selected or configured default release when a conversation is
created. On turn acceptance the API creates an immutable run snapshot. The generic workflow then
uses only that snapshot for model and tool calls, ordered events, cancellation, retry, and final
response persistence.

Mutable catalog state never changes accepted work. Publishing, deprecating, or changing a default
affects only future selection. Existing conversations keep their selected release and accepted
turns keep their original snapshot.

## Agent lifecycle

Declarative packages can enter through two adapters:

- filesystem/CLI publication from `agents/<agent-id>/<version>/manifest.json`;
- portal drafts composed of immutable revisions, validation results, and private test sessions.

Both adapters converge on one publication service and the same canonical manifest, artifact,
digest, grant, release, and audit contracts. Publication is transactional, idempotent for identical
content, and conflicting for changed content under an existing version.

Portal authoring separates `genai-agent-author` from `genai-agent-publisher`. Drafts and draft-test
conversations are owner-only and absent from ordinary catalogs. Publication repeats validation
inside the transaction instead of trusting a previous UI or test result.

## Trust boundaries

- Browser input and bearer tokens terminate at the Portal API.
- User identity is derived from a validated Keycloak token, never a request-body owner field.
- Agent manifests, instructions, prompts, tool arguments/results, and provider payloads are
  untrusted and bounded.
- The application sends only reviewed tool definitions and enforces exact grants on every call.
- MCP services receive no browser bearer token or platform database credential.
- Agent workers receive immutable run data; they do not mount repository agent source.
- Secrets stay in environment/runtime configuration and are redacted from logs, events, traces,
  audit data, and artifacts.

## Persistence invariants

- Published versions and canonical artifacts are immutable.
- Accepted run snapshots are immutable and self-contained.
- Idempotency keys prevent duplicate turn acceptance and publication.
- Ordered events can be replayed over SSE after reconnect.
- One accepted turn produces at most one terminal assistant response.
- Owner checks apply to every read and mutation, including draft tests and audit access.
- Migrations are additive while retained rows depend on the newer schema.

## Operational boundaries

The supported local deployment is Docker Compose on Linux with standalone Keycloak. Portal traffic
uses local TLS. Databases, Temporal, Agentgateway, MCP servers, and observability dependencies stay
on private networks except for explicitly exposed local operator interfaces.

The next proposed trust boundary—isolated execution of independently supplied Python code—is not
implemented. Its threat model and acceptance gates are in
[Executable agent isolation](architecture/INCREMENT10_PLAN.md).
