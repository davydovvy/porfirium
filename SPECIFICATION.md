# Porfirium — Architecture and Delivery Specification

Status: Implemented Phase 0–4 baseline; architecture transition in progress
Last updated: 2026-08-22
Implementation status: Phases 0–4 and transition Increments 0–5 implemented and accepted

> **Current architecture overlay:** The staged replacement of both Bifrost gateway roles with Agentgateway, together with the introduction of independently publishable and immutable agent versions, is defined in [Agentgateway and Versioned Agent Platform Transition Plan](docs/architecture/AGENTGATEWAY_AGENT_PLATFORM_TRANSITION.md). Increments 3–5 are accepted, so Agentgateway is the sole MCP and model provider and Bifrost has been retired. Bifrost-specific sections below describe the accepted Phase 0–4 baseline and remain historical regression evidence.

Transition acceptance evidence is recorded in [Architecture Transition Results](docs/architecture/TRANSITION_RESULTS.md). Increment 0, the complete live Bifrost-era migration regression baseline, passed and was accepted on 2026-08-21.

Increment 1, the vendor-neutral model/tool gateway seam with Bifrost adapters, passed the same complete live regression gate and was accepted on 2026-08-21. Increment 2, the pinned side-by-side Agentgateway/Yandex compatibility spike, also passed on 2026-08-21. Increments 3 and 4 cut MCP and LLM traffic over on 2026-08-22. Increment 5 retired Bifrost from current paths after the complete Agentgateway gate passed.

## 1. Purpose

Build a local-first demonstration platform where an authenticated user can:

- chat directly with a cloud-hosted LLM;
- chat with a durable, tool-using agent;
- observe agent steps, LLM calls, and tool calls in Langfuse;
- demonstrate tools exposed by independently deployed MCP servers;
- later add skills whose scripts execute in isolated sandboxes.

RAG, document ingestion, vector storage, and semantic search are explicitly out of scope for the first version.

## 2. Goals and success criteria

### 2.1 Goals

- Use the standalone Keycloak installation in `/home/dvy/Projects/KeyCloak` as the identity provider.
- Provide a React chat UI backed by a FastAPI API.
- Route every application LLM request through Bifrost to Yandex Cloud.
- Run durable agent orchestration with Temporal and Python.
- Expose selected standalone MCP servers through Bifrost's MCP gateway interface.
- Correlate a user chat turn across the portal, agent, LLM, and tool traces.
- Establish extension contracts for later skills and sandboxed scripts without implementing them now.
- Make the entire demo reproducible and understandable to a developer on one workstation.

### 2.2 Demo acceptance criteria

1. A demo user signs in through Keycloak and signs out successfully.
2. The user starts a conversation and selects either `Direct LLM` or `Agent`; later versions can expose concrete model and agent choices.
3. Direct mode streams a Yandex-hosted model response through Bifrost to the browser.
4. Agent mode starts a Temporal workflow, streams visible progress, invokes at least one MCP tool, and returns a final answer.
5. Refreshing the browser preserves the conversation and can reconnect to an in-progress agent run.
6. A trace can be found in Langfuse using a conversation ID, turn ID, workflow ID, or pseudonymous user ID.
7. Stopping and restarting a Temporal worker does not lose an accepted agent run.
8. MCP tools unavailable to a user or agent cannot be invoked merely by prompting the model.
9. Secrets are supplied at runtime and are absent from Git and browser responses.

## 3. Scope

### 3.1 First release

- React single-page application.
- FastAPI portal/backend-for-frontend (BFF).
- OIDC Authorization Code flow with PKCE against local Keycloak.
- Conversation and message persistence.
- Direct LLM chat with token streaming.
- Python agent worker and Temporal workflows/activities.
- Bifrost LLM and MCP gateway capabilities.
- Yandex Cloud LLM provider configuration.
- Pinned self-hosted Langfuse with its dedicated backing services.
- Two small, read-only-first demo MCP servers in separate containers.
- Docker Compose-based local runtime, while Keycloak remains in its standalone project.
- Health checks, structured logs, trace correlation, and a repeatable demo script.

### 3.2 Explicitly deferred

- RAG, embeddings, vector databases, document ingestion, and reranking.
- Production Kubernetes deployment and high availability.
- Multi-tenant billing or quotas.
- Full admin portal.
- Training or fine-tuning models.
- Arbitrary user-authored skill installation.
- Production-grade sandbox implementation.
- Voice, image, and file-upload workflows unless later added to scope.

## 4. System context

```text
Browser
  │ OIDC login                      Standalone project
  ├───────────────────────────────► Keycloak
  │                                  https://keycloak.local:8443
  │ HTTPS/SSE
  ▼
React UI ──► FastAPI Portal API ───────┬──► Bifrost LLM API ──► Yandex Cloud LLM
                                      │
                                      ├──► Temporal Server ◄── Python Agent Worker
                                      │                         │
                                      │                         ├──► Bifrost LLM API
                                      │                         └──► Bifrost MCP API
                                      │                                  │
                                      │                                  ├──► Demo MCP Server A
                                      │                                  └──► Demo MCP Server B
                                      │
                                      ├──► Application PostgreSQL
                                      └──► Langfuse / OTLP

FastAPI, agent workers, and gateway instrumentation propagate shared trace context.
```

Keycloak is not included in this repository's Compose lifecycle. The standalone Keycloak project owns the implemented realm named exactly `GenAI-platform`, giving the issuer `https://keycloak.local:8443/realms/GenAI-platform`. The Keycloak development endpoint remains `http://localhost:8180`. Dedicated `genai-demo-web` and `genai-demo-api` clients and platform roles are configured in this realm. Local containers and host applications trust the existing demo root CA.

## 5. Architecture decisions

The following decisions are accepted unless explicitly reopened.

### AD-01: One Bifrost deployment, two logical gateway roles — Accepted

Use one Bifrost process/container for the demo and treat its OpenAI-compatible LLM API and MCP API as separate trust boundaries in configuration and code. Split them into independent deployments later if scaling, ownership, or security requires it.

Rationale: Bifrost currently provides both LLM gateway and MCP client/server capabilities. One deployment reduces demo overhead while preserving logical separation.

### AD-02: Application-controlled tool loop — Accepted

The Python agent worker owns the reasoning/tool loop. It asks the LLM for tool calls through Bifrost, validates the requested tool against policy, executes it through Bifrost MCP, records the result, and continues. Do not enable blanket Bifrost auto-execution in the first release.

Rationale: Temporal can durably record orchestration, while the application retains authorization, approval, timeout, and audit control.

### AD-03: Temporal workflows orchestrate; activities perform I/O

Workflow code contains deterministic state transitions only. LLM requests, MCP calls, persistence operations, and future sandbox execution occur in activities. Payloads stored in Temporal history should contain references or bounded summaries rather than large prompts/results.

### AD-04: FastAPI is the only browser-facing application API

The browser never calls Temporal, Bifrost, MCP servers, Langfuse, or Yandex Cloud directly. FastAPI validates Keycloak tokens and enforces ownership and role checks.

### AD-05: Server-Sent Events for first-release streaming

Use SSE for token and status delivery. Keep commands such as cancel, retry, approve, and submit message as ordinary authenticated HTTP requests. Consider WebSockets only if bidirectional real-time requirements become material.

### AD-06: OpenTelemetry-compatible correlation

Adopt W3C trace context at HTTP boundaries and propagate correlation metadata into Temporal workflow/activity headers. Use the current Langfuse Python SDK/OTLP model for application and agent observations. A chat turn is the top-level logical trace; LLM generations and MCP executions are child observations.

### AD-07: Persist product state outside Temporal

Use an application PostgreSQL database for conversations, messages, turns, agent-run projections, and audit metadata. Temporal is the durable execution log, not the query model for the UI.

### AD-08: Stable internal contracts, vendor adapters at the edges

Portal and agent code use internal `ModelGateway`, `ToolGateway`, `TraceSink`, and future `SandboxExecutor` interfaces. Bifrost-, Langfuse-, and Temporal-specific details remain in adapters.

### AD-09: Self-host Langfuse locally — Accepted

Langfuse and its required backing services run locally as part of this repository's Compose topology. Langfuse is a core demo component, not an optional cloud dependency. Its UI is exposed only on localhost and its ingestion endpoint is available on the private application network.

### AD-10: Use the host's available compute — Accepted

Do not configure artificial Docker CPU or memory limits for the demo services. Docker may schedule across all resources visible on this laptop: 16 logical CPUs (AMD Ryzen 7 8845H, 8 cores/16 threads) and approximately 27.1 GiB of RAM. Service-level concurrency, payload, history, and timeout limits still apply because they protect correctness and upstream cost rather than reserve host capacity.

### AD-11: Auto-execute policy-approved read-only tools — Accepted

Read-only MCP tools execute without user approval after server-side policy validation. The agent must still validate the user, selected agent, tool identity, arguments, and versioned allowlist before every call. Unknown, denied, or non-read-only tools fail closed. Future tools with side effects require a separate policy and may introduce approval.

### AD-12: Agent status streaming with atomic final response — Accepted

Agent mode emits lifecycle and tool-status events while it runs, followed by one complete final assistant response. It does not stream partial LLM tokens to the browser. Direct LLM mode continues to support token streaming.

### AD-13: Multi-user isolation is a visible demo requirement — Accepted

The platform supports multiple Keycloak users with isolated conversations, turns, runs, event streams, and tool/audit records. The demo and automated tests must visibly prove that one user cannot enumerate, read, modify, stream, cancel, or retry another user's resources.

### AD-14: Persist conversations without user deletion — Accepted

Conversations and messages persist across ordinary container and host restarts using named volumes and database migrations. The first-release UI and API do not support conversation deletion. A separately documented operator reset may erase all demo state, but it is an explicit destructive maintenance action rather than a product feature.

### AD-15: Simple initial mode selection with extensible catalogs — Accepted

The first UI asks the user to choose only `Direct LLM` or `Agent`. Direct mode uses the configured default model and agent mode uses the configured default agent. The capabilities API and stored turn metadata are designed so a later release can expose a model selector for direct chat and an agent selector populated from the available-agent catalog without changing the conversation model.

### AD-16: Future skills must eventually cover both trust levels — Accepted, details deferred

The future skill architecture must accommodate both administrator-authored trusted scripts and user-supplied untrusted code. Decisions about networking, artifacts, secrets, package installation, internal-service access, and the concrete sandbox technology are intentionally postponed. No first-release implementation may assume trusted-only execution.

### AD-17: Capture rich synthetic demo traces — Accepted

Langfuse stores as much useful information as supported for synthetic demo data, including prompts, completions, tool arguments/results, model and token metadata, agent status, timing, errors, and correlation identifiers. Credentials, access tokens, cookies, private keys, and infrastructure secrets remain prohibited. Real or sensitive data requires a later privacy and retention review.

### AD-18: Linux-only, HTTPS-preferred, permissive-license-first — Accepted

Linux is the only supported host. Local HTTPS is preferred for the portal as well as required for the canonical Keycloak origin. Prefer Apache-2.0 or MIT licensed products and libraries. Before implementation, produce a dependency/license inventory; permissively licensed compatible substitutes should be considered, and unavoidable exceptions must be explicitly recorded and accepted.

### AD-19: Every implementation phase produces a user-testable increment — Accepted

Implementation is delivered phase by phase. At the end of each phase, the current platform must be runnable on this laptop, demonstrated to the user, and left available for hands-on use. The next phase does not begin until the phase's results, known limitations, startup instructions, and verification evidence have been presented and the user has had an opportunity to review the increment.

## 6. Component specifications

### 6.1 Web portal frontend

Technology: React + TypeScript; build tooling and component library to be selected during implementation planning.

Responsibilities:

- initiate OIDC Authorization Code + PKCE login;
- show user identity and permitted modes/agents;
- list, create, rename, and revisit persistent conversations; deletion is not exposed;
- render streaming assistant tokens and agent status events;
- distinguish direct LLM messages, reasoning status, tool requests, tool results, and errors;
- allow cancel/retry; approval UI is deferred until tools requiring approval enter scope;
- reconnect to a turn stream after refresh or transient network loss;
- never store provider credentials or privileged service tokens.

Proposed main routes:

- `/login/callback`
- `/chat/new`
- `/chat/:conversationId`
- `/runs/:runId` (optional diagnostic view)

### 6.2 Portal API (FastAPI)

Responsibilities:

- validate JWT signature, issuer, audience, expiry, and required roles against Keycloak metadata/JWKS;
- map the Keycloak subject to an internal pseudonymous user identifier;
- enforce conversation/run ownership;
- persist conversations, messages, and turn projections;
- call Bifrost directly for direct-chat mode;
- start, signal/update, query, and cancel Temporal workflows for agent mode;
- expose an SSE stream backed by persisted events plus live notifications;
- create trace roots and propagate correlation identifiers;
- normalize upstream errors into stable application errors.

Proposed API surface (draft):

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/me` | Current identity and capabilities |
| `GET/POST` | `/api/v1/conversations` | List or create conversations |
| `GET/PATCH` | `/api/v1/conversations/{id}` | Read or rename one conversation; deletion is not supported |
| `POST` | `/api/v1/conversations/{id}/turns` | Submit a direct or agent turn |
| `GET` | `/api/v1/turns/{id}` | Current durable turn projection |
| `GET` | `/api/v1/turns/{id}/events` | Replayable SSE event stream |
| `POST` | `/api/v1/turns/{id}/cancel` | Request cancellation |
| `POST` | `/api/v1/tool-requests/{id}/decision` | Reserved for a future approval policy |
| `GET` | `/api/v1/capabilities` | Default mode configuration plus model/agent catalogs reserved for later selectors |
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Dependency-aware readiness |

The turn submission request includes an idempotency key. The response returns `turn_id`, mode, current state, and event-stream URL.

### 6.3 Agent backend

Technology: Temporal Python SDK and one or more Python workers.

Initial agent: `tool_assistant_v1`, a bounded conversational agent capable of selecting approved read-only tools and synthesizing a final response.

Proposed workflow contract:

```text
AgentRunInput
  run_id, conversation_id, turn_id, user_ref
  agent_name, agent_version, model_alias
  messages/reference, policy_snapshot, trace_context

AgentRunResult
  status, final_message_id, usage_summary
  tool_call_summary, error_code
```

Workflow states:

```text
ACCEPTED → RUNNING → COMPLETED
           ├────────► CANCELLED
           └────────► FAILED
```

Activities:

- load bounded conversation context;
- request an LLM completion through Bifrost;
- validate a tool call against the run's policy snapshot;
- execute an MCP tool through Bifrost;
- persist progress and final messages;
- emit/update Langfuse observations;
- later, invoke a sandbox executor for a versioned skill script.

Operational rules:

- set explicit activity timeouts and bounded retries;
- use deterministic workflow IDs derived from the run ID;
- make activities idempotent using run/step/call identifiers;
- cap agent iterations, elapsed time, tool calls, tokens, and result size;
- emit bounded status events during execution and persist the final assistant response atomically;
- support cancellation and heartbeat long-running activities;
- use versioning/patching for workflow changes that affect open executions;
- do not record secrets in workflow inputs, results, logs, or search attributes.

### 6.4 Bifrost LLM gateway

Responsibilities:

- present one OpenAI-compatible endpoint to portal and agent services;
- route stable application model aliases to Yandex Cloud model identifiers;
- hold provider credentials outside application code;
- enforce request timeouts, retry policy, concurrency limits, and optional budgets;
- report model, latency, token usage, and errors for tracing;
- redact sensitive headers and configured content fields from logs.

Yandex integration is based on the proven configuration in `/home/dvy/Projects/mcpcontext-demo`:

```text
base URL: https://ai.api.cloud.yandex.net/v1
model:    gpt://<folder-id>/deepseek-v4-flash/latest
auth:     server-held service-account API key
header:   no separate folder header
```

Use the OpenAI-compatible Responses API as the canonical application-to-Bifrost contract. Chat Completions remains enabled only as a temporary compatibility fallback. The Phase 0 spike verifies non-streaming Responses, semantic SSE streaming, strict JSON Schema output, a forced MCP function call, MCP execution, stateless continuation with a function result, token usage, and Langfuse ingestion.

Configure Yandex as a named Bifrost custom provider with `base_provider_type: openai` and explicit `/v1/responses` and `/v1/chat/completions` path overrides. Automatic MCP tool injection must be disabled globally; the trusted backend supplies a per-request allowlist after policy evaluation. Conversation history remains authoritative in the platform database: do not depend on Yandex `previous_response_id` or provider-side conversations. Provider response IDs may be retained as trace metadata. The service account must have `ai.languageModels.user`, and its API key should be restricted to `yc.ai.languageModels.execute`.

Yandex configuration, including its API key, lives only in this project's ignored `.env`. Do not copy its secret value into tracked configuration, Compose YAML, documentation, images, or browser-visible data.

Selected initial aliases:

- `chat-default` — `deepseek-v4-flash/latest` for direct chat;
- `agent-default` — `deepseek-v4-flash/latest`, already verified for tool calling in the reference project;
- `chat-fast` — optional lower-latency/lower-cost model.

Application code must use aliases rather than Yandex-specific model URIs.

### 6.5 Bifrost MCP gateway

Responsibilities:

- connect to standalone MCP servers over a network transport supported by the pinned version;
- discover tools and expose a unified execution surface;
- apply an allowlist per agent and environment;
- bound request duration and response size;
- preserve tool name/server identity in traces and audit records;
- permit automatic execution only for explicitly reviewed, policy-allowlisted read-only tools.

The agent backend, not the LLM, is the authorization authority. A tool appearing in an LLM response is only a request until policy validation succeeds. In the first release, allowlisted read-only tools execute automatically after validation; no user approval step is required.

### 6.6 Demo MCP servers

Each server is an independent container, owns its dependencies, exposes a health check, and uses a network HTTP transport suitable for container-to-container access.

Demonstrations:

1. `demo-time-mcp`: read-only tools for current time and timezone conversion. This demonstrates deterministic schemas and a simple external-style lookup without credentials. Its reviewed tools may execute without user approval.
2. `demo-mtg-catalog-mcp`: read-only tools over a bundled catalog of approximately 100 popular Magic: The Gathering cards. This demonstrates structured filtering, lookup, comparison, and a multi-step agent interaction without introducing RAG. Its reviewed tools may execute without user approval.

The MTG catalog contains exactly 20 curated popular cards from each of five representative sets released from 2010 through 2014:

| Year | Set | Initial set code |
|---|---|---|
| 2010 | Magic 2011 | `M11` |
| 2011 | Innistrad | `ISD` |
| 2012 | Return to Ravnica | `RTR` |
| 2013 | Theros | `THS` |
| 2014 | Khans of Tarkir | `KTK` |

Final card selection is a checked-in, versioned dataset reviewed before implementation. Each record includes:

- card name, set name/code, collector number, release year, and rarity;
- mana cost, mana value, colors/color identity, card types/subtypes, rules text, power/toughness or loyalty when applicable;
- one illustrative market-price snapshot with currency, price basis/condition, source attribution, and `captured_at` date;
- optional image/reference URL only if its use and attribution comply with the chosen data source's terms.

Prices are static demo snapshots, not live quotes, purchasing advice, or guaranteed valuations. The repository must document the dataset source, attribution, permitted use, and refresh procedure. Card text, images, symbols, and trademarks require a data/IP review distinct from the software-license inventory.

Initial tool surface:

- `search_cards(query, set_code?, colors?, card_type?, rarity?, min_price?, max_price?, limit?)`;
- `get_card(card_id)`;
- `compare_cards(card_ids)` with a small bounded list;
- `list_sets()`.

Constraints:

- no host filesystem or Docker socket mounts;
- no arbitrary URL fetching in the first release;
- non-root runtime, read-only root filesystem where practical;
- fixed output-size and execution-time limits;
- structured errors and input validation;
- explicit tool names, descriptions, JSON schemas, and version metadata.

### 6.7 Langfuse (self-hosted)

Responsibilities:

- trace a complete turn from API receipt through agent steps, generations, and tools;
- associate traces with session/conversation and pseudonymous user IDs;
- record model, latency, usage, errors, agent/tool versions, and environment;
- support later prompt versioning and evaluation without requiring it in release one.

Deployment requirements:

- run the official self-hosted topology and required backing services at pinned versions;
- keep Langfuse application data logically isolated from application and Temporal persistence;
- expose the UI on localhost only;
- use private-network ingestion URLs from application containers;
- add dependency health checks and startup ordering based on readiness, not fixed sleeps;
- include Langfuse storage in the documented local reset and backup policy.

Tracing content policy for this synthetic demo:

- capture complete prompts and completions;
- capture bounded MCP arguments and results;
- capture agent/model/tool versions, token usage, timing, errors, and correlation metadata;
- centrally redact authentication material and secrets before export;
- document that this permissive capture policy applies only to synthetic demo content.

Data policy:

- default to capturing metadata and redact credentials/authorization headers;
- make prompt/completion capture configurable by environment;
- never send raw Keycloak access tokens;
- define retention before using real or sensitive data;
- use a pseudonymous stable user reference, not username/email, in traces.

### 6.8 Data storage

Application PostgreSQL logical schema:

- `users`: internal ID, Keycloak subject, timestamps;
- `conversations`: owner, title, mode defaults, timestamps;
- `messages`: role, bounded content, status, sequence, metadata;
- `turns`: mode, agent/model alias, status, idempotency key, correlation IDs;
- `turn_events`: ordered replayable UI events with monotonic sequence;
- `agent_runs`: Temporal namespace/workflow/run references and projection;
- `tool_requests`: server/tool, arguments policy metadata, decision, result reference;
- `audit_events`: security-relevant actions and outcome.

Use separate databases or schemas and credentials for application, Temporal, and self-hosted Langfuse data. Do not let services share an unrestricted database identity.

## 7. Authentication and authorization

### 7.1 Keycloak integration

Create these dedicated client registrations in the new `GenAI-platform` realm:

- `genai-demo-web`: public OIDC client, Authorization Code + PKCE, strict local redirect URIs and web origins;
- `genai-demo-api`: API audience/resource indicator if required by the realm's token model;
- optional service clients only if machine-to-machine authentication is introduced.

Proposed realm roles:

- `genai-user`: use direct chat and allowed agents;
- `genai-tool-approver`: reserved for future approval-required tools; not needed for the initial read-only tools;
- `genai-admin`: view diagnostic configuration, not provider secrets.

The BFF validates tokens locally using cached JWKS. It does not forward browser bearer tokens to Bifrost, Temporal, MCP servers, Yandex, or Langfuse.

### 7.2 Service trust for local demo

Use private Compose networking and service-specific credentials/API keys where supported. Bind infrastructure admin interfaces to localhost only. Caddy terminates portal HTTPS at `https://portal.local:8444` using its persistent local development CA; the Keycloak CA is trusted wherever the HTTPS issuer is used. The canonical issuer remains `https://keycloak.local:8443/realms/GenAI-platform` in both browser and backend validation paths.

### 7.3 Tool authorization

Effective access is the intersection of:

```text
user roles ∩ selected agent policy ∩ environment allowlist ∩ tool risk policy
```

Policy is evaluated before every call and stored as a versioned snapshot/reference for audit. Prompt instructions cannot expand it.

For the initial MCP servers, a successful policy decision immediately authorizes execution because all exposed tools are classified as read-only. Classification is configuration controlled, not inferred from a tool description or model output.

### 7.4 Multi-user isolation

- derive ownership from the validated Keycloak `sub` claim, never a client-supplied user identifier;
- scope every product-data query by internal user ID, including event replay and cancellation;
- return a non-enumerating response for resources owned by another user;
- do not expose another user's resource identifiers through ordinary-user lists, traces, logs, or errors;
- use separate browser sessions for the two-user demo and explicitly test direct object-reference attacks;
- keep administrator access to user data out of scope unless a later requirement defines it.

## 8. Streaming, durability, and error behavior

### 8.1 Event model

Suggested SSE event types:

- `turn.accepted`
- `assistant.delta` (direct LLM mode only)
- `agent.status`
- `tool.requested`
- `tool.started`
- `tool.completed`
- `turn.completed`
- `turn.failed`
- `turn.cancelled`
- `stream.heartbeat`

Every event has `event_id`, `turn_id`, monotonically increasing `sequence`, timestamp, type, and a typed payload. The API honors `Last-Event-ID` or an equivalent sequence query for replay. Agent mode emits status/tool events followed by a single `turn.completed` event containing or referencing the complete persisted final response; it does not emit `assistant.delta` events.

### 8.2 Failure semantics

- A client disconnect does not cancel the underlying direct/agent turn by default.
- Direct-mode execution should also have a persisted state projection, even though it does not require Temporal.
- Retriable upstream errors expose a stable public error code and correlation ID.
- Retrying a submitted turn with the same user-scoped idempotency key returns the original turn.
- Partial assistant text remains marked incomplete on failure or cancellation.
- Tool failures are returned to the agent only in bounded, sanitized form.

## 9. Future skills and sandbox extension

No sandbox executor or skill runtime is implemented in the first release. The design reserves these concepts:

```text
SkillManifest
  name, version, description
  input_schema, output_schema
  required_capabilities
  script/image reference and immutable digest
  resource limits, timeout, network policy

SandboxExecutionRequest
  execution_id, skill digest, validated input
  policy snapshot, trace context, artifact limits

SandboxExecutionResult
  status, validated output, bounded logs
  artifact references, usage, policy violations
```

Future rules:

- execute scripts in a separate sandbox service/activity, never inside a Temporal workflow process, portal API, Bifrost container, or general agent worker;
- pin every execution to an immutable skill version/digest;
- deny network, host mounts, privilege escalation, and ambient credentials by default;
- use ephemeral filesystem and process/container/microVM isolation based on the eventual threat model;
- enforce CPU, memory, process, wall-time, output, and artifact limits;
- broker explicitly allowed network/API capabilities rather than inject broad credentials;
- validate inputs and outputs against schemas;
- record provenance and trace metadata without leaking secrets;
- require review/signing before a skill enters the trusted catalog.

The future sandbox technology is deliberately not selected yet. Docker alone may be acceptable for trusted demo scripts but should not be assumed sufficient for hostile multi-tenant code.

The eventual design must support both trusted administrator-authored and untrusted user-supplied skills. All capability choices beyond today's deny-by-default boundary are deferred to a dedicated future threat-modeling and sandbox-design phase.

## 10. Repository and deployment plan

Current and evolving monorepo layout:

```text
genai-demo-platform/
  docs/
    architecture/
    decisions/
    demo-runbook.md
  apps/
    web/                    # React/TypeScript
    portal-api/             # FastAPI
  services/
    agent-worker/           # Temporal Python worker
    mcp-time/               # standalone image/context
    mcp-mtg-catalog/        # standalone image/context and versioned card data
  packages/
    python-contracts/       # shared typed contracts; keep small
  deploy/
    compose/
    bifrost/
    temporal/
    langfuse/
  scripts/                  # developer lifecycle scripts, not agent skills
  tests/
    integration/
    e2e/
  .env.example
  compose.yaml
  Makefile (or task runner)
```

Keycloak remains at `/home/dvy/Projects/KeyCloak` and is documented as a prerequisite. Its project owns the `GenAI-platform` realm export/configuration; this repository does not duplicate or start the Keycloak stack.

Application database and conversation data use persistent named volumes and survive ordinary `docker compose down`/`up` cycles and host restarts. The runbook distinguishes normal stop/start from an explicit full-state reset. There is no user-facing conversation deletion operation in the first release.

Suggested local network exposure:

- web portal: browser-accessible;
- portal API: browser-accessible or same-origin proxied;
- Keycloak: existing `https://keycloak.local:8443`;
- Langfuse UI: localhost-only;
- Temporal UI: localhost-only;
- Bifrost admin UI: localhost-only;
- Bifrost APIs, Temporal service, databases, and MCP servers: private Compose network unless debugging requires an explicit localhost bind.

The browser origin is `https://portal.local:8444`, terminated by Caddy with a persistent local development CA. Phase 1 verifies OIDC redirects and protected same-origin API routing through that origin; SSE verification arrives with direct chat in Phase 2.

No Compose CPU or memory limits are applied. The baseline host measured during planning has 16 logical CPUs and 27.1 GiB RAM. The runbook should include an idle and active resource snapshot once the full self-hosted stack exists, but no lower resource target is an acceptance constraint for this laptop.

## 11. Delivery phases

### 11.1 Mandatory phase handoff

Every implementation phase below ends with the same handoff gate:

1. Start the complete platform increment on the user's laptop, including all components required by that phase.
2. Run automated checks and a phase-specific smoke test; present their actual results rather than only stating that they passed.
3. Demonstrate the new behavior through the browser and relevant observability/admin UI where applicable.
4. Provide exact start, stop, status, and recovery commands plus any required local URLs and demo credentials or user setup procedure. Never expose secrets in the handoff.
5. Leave the increment in a usable state so the user can exercise it independently after the demonstration.
6. Summarize completed scope, deferred scope, known issues, resource usage, and any deviations from this specification.
7. Collect user feedback and obtain confirmation before beginning the next implementation phase.

A phase is not complete if only backend code or isolated tests work while the user-facing increment cannot be run. Later phases must preserve the usable behavior delivered by earlier phases.

### Phase 0 — Decisions and connectivity spikes

- resolve all blocking questions in section 14;
- pin supported component versions and licenses;
- validate Keycloak client/audience/TLS behavior from browser and container;
- validate Bifrost → Yandex streaming and tool-call compatibility;
- validate Bifrost MCP connectivity to one containerized HTTP MCP server;
- validate the pinned self-hosted Langfuse topology and decide its data-capture policy;
- inventory direct runtime components and licenses, including Langfuse backing services, and record any non-Apache-2.0/MIT exception;
- confirm the MTG dataset source, attribution, static price basis, and permitted use;
- record findings as architecture decision records.

Exit: each external integration has a minimal, documented proof, including the known Yandex contract reproduced through Bifrost, and the runtime topology is agreed.

User-testable result: a connectivity/diagnostics package and runbook that the user can run to inspect Keycloak reachability, Yandex-through-Bifrost completion/tool compatibility, Bifrost MCP discovery, local Langfuse health, licenses, and the selected MTG dataset manifest. Phase 0 may use diagnostic commands rather than the final portal, but results must be reproducible by the user.

### Phase 1 — Platform skeleton and identity

- establish monorepo conventions, dependency locking, configuration, and Compose profiles;
- add React shell and FastAPI health/config endpoints;
- register dedicated Keycloak clients/roles and implement login/token validation;
- add application database migrations and core conversation model;
- add CI checks, secret scanning, and baseline tests.

Exit: an authenticated user can access an empty conversation UI and unauthorized access is rejected.

User-testable result: the user can start the platform, open the HTTPS portal, sign in as either of at least two demo users, see their identity, sign out, and verify that protected routes reject an unauthenticated session.

### Phase 2 — Direct LLM chat

- configure Bifrost and Yandex provider/model aliases;
- implement conversation/turn APIs, persistence, SSE replay, and cancellation;
- implement direct streaming chat;
- instrument portal and gateway path in Langfuse;
- add timeout, retry, redaction, and public error handling.

Exit: acceptance criteria 1, 2, 3, 5, 6, and 9 pass for direct mode.

User-testable result: the user can create persistent conversations, select `Direct LLM`, receive a streamed Yandex response, revisit history after restart, and locate the complete synthetic trace in Langfuse. The UI does not expose conversation deletion.

### Phase 3 — Durable agent

- deploy/configure Temporal locally;
- implement versioned agent workflow and I/O activities;
- project run events into the application database/SSE stream;
- implement restart recovery, idempotency, limits, cancellation, and trace propagation;
- add agent selection and progress rendering.

Exit: a no-tool agent run survives worker restart and is fully traceable.

User-testable result: the user can select `Agent`, observe durable status events followed by one complete response, reconnect after a browser refresh, inspect the Temporal workflow and Langfuse trace, and verify that a worker restart does not lose the run.

### Phase 4 — MCP tools and policy

Implementation note: delivered and accepted on 2026-08-19. Reproducible evidence and as-built details are recorded in [the Phase 4 results](docs/phase4/RESULTS.md).

- implement/package the two demo MCP servers;
- register them with Bifrost MCP gateway;
- implement explicit tool-call validation and execution activities;
- add allowlists and automatic execution for policy-approved read-only tools; reserve an approval state for future sensitive tools;
- trace and audit tool requests/results;
- test prompt-based attempts to invoke unauthorized tools.

Exit: acceptance criteria 4, 7, and 8 pass; both demo tools are repeatable.

User-testable result: the agent automatically invokes policy-approved time and MTG catalog tools, shows tool-status events, and returns a final answer. The user can try catalog search, card detail, comparison, and price questions, inspect traces, and verify cross-user isolation with two accounts.

### Phase 5 — Hardening and demo readiness

- add end-to-end tests, dependency failure tests, and a smoke test;
- cap context, tokens, loops, tool results, and concurrent work;
- verify log/trace secret and PII redaction;
- document setup, teardown, reset, troubleshooting, and demo narrative;
- capture known production gaps and future sandbox backlog.

Exit: a new developer can run the documented demo from a clean checkout with separately started Keycloak.

User-testable result: the complete scripted demo runs from documented commands, exposes all agreed UIs over the intended local origins, reports component health and resource usage, and includes failure/recovery exercises the user can repeat.

## 12. Test strategy

- Unit: policy evaluation, state transitions, adapters, schema validation, redaction.
- Contract: portal API/OpenAPI, Bifrost LLM responses, MCP tool schemas, workflow input/result compatibility.
- Integration: Keycloak JWT validation, Bifrost/Yandex, Temporal restart/retry, PostgreSQL migrations, Langfuse export.
- End-to-end: login → direct turn; login → agent status → automatically executed read-only tool → complete answer; refresh/reconnect; cancel; two-user isolation.
- Resilience: worker termination, MCP timeout, malformed tool result, Bifrost unavailable, Yandex rate limit, Langfuse unavailable.
- Security: expired/wrong-audience token; cross-user list/read/update/delete/stream/cancel/retry attempts; tool allowlist or read-only classification bypass; prompt injection; oversized input/output; secret leakage.

Observability must fail open for product requests: Langfuse unavailability should not break chat, though it must produce a visible operational signal.

## 13. Configuration and secrets inventory

Names are illustrative and should be finalized with the implementation.

```text
KEYCLOAK_ISSUER=https://keycloak.local:8443/realms/GenAI-platform
KEYCLOAK_AUDIENCE
KEYCLOAK_JWKS_CACHE_TTL
DATABASE_URL
TEMPORAL_ADDRESS
TEMPORAL_NAMESPACE
TEMPORAL_TASK_QUEUE
AGENTGATEWAY_URL=http://agentgateway:8090
TOOL_GATEWAY_TIMEOUT_SECONDS
YANDEX_OPENAI_BASE_URL=https://ai.api.cloud.yandex.net/v1
YANDEX_API_KEY
YANDEX_MODEL=gpt://<folder-id>/deepseek-v4-flash/latest
LANGFUSE_BASE_URL
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_TRACING_ENVIRONMENT
```

Commit only `.env.example` placeholders. Prefer a local secret file excluded by Git for the demo and document the migration path to a secret manager.

## 14. Decision record and deferred questions

### Resolved decisions

1. Langfuse is self-hosted locally as a core Compose component.
2. Yandex uses `https://ai.api.cloud.yandex.net/v1`, a server-held service-account API key, and `gpt://<folder-id>/deepseek-v4-flash/latest`, following the verified reference project contract.
3. Keycloak uses a new realm named exactly `GenAI-platform` with dedicated platform clients and roles.
4. One Bifrost instance provides both LLM and MCP capabilities through separate logical interfaces.
5. The stack may use all resources on the laptop; no Docker CPU/RAM caps are required. The measured host has 16 logical CPUs and 27.1 GiB RAM.

### Resolved product decisions

6. Policy-approved read-only MCP tools execute without user approval.
7. Agent mode streams status events followed by one complete final response; it does not stream tokens.
8. The platform supports multiple users with isolated conversations, and the demo visibly proves this boundary.

9. Conversations persist across ordinary restarts. User-facing deletion is not required.
10. The initial UI selects only direct versus agent mode. Later releases add a direct-chat model selector and an available-agent selector.
11. The catalog demo contains approximately 100 popular MTG cards: 20 each from `M11`, `ISD`, `RTR`, `THS`, and `KTK`, including attributes and dated price snapshots.
12. Future skills must support both administrator-authored trusted scripts and user-supplied untrusted code.
13. Detailed skill capabilities and sandbox choices are postponed to a future design phase.
14. Langfuse captures as much synthetic demo information as possible, excluding secrets and authentication material.
15. Linux is the only supported host; local HTTPS for the portal is preferred.
16. Apache-2.0 and MIT are the preferred software licenses. There are no additional data-residency, offline-operation, or corporate-proxy constraints.
17. MinIO is accepted as a documented AGPL-3.0 license exception for the local demo because it preserves the supported self-hosted Langfuse topology. It is not exposed as a platform product feature, and this acceptance does not imply approval for a production redistribution model.

### Explicitly deferred

- sandbox technology and isolation strength for trusted versus untrusted skills;
- skill access to networks, secrets, package installation, persistent artifacts, and internal services;
- production privacy/retention policy for non-synthetic data;
- the model and agent selector user experience beyond the reserved capability contracts.

## 15. Consolidated implementation baseline

The implementation plan uses the following agreed baseline:

- one workstation and Docker Compose with no CPU/RAM caps;
- a single Bifrost deployment with logically separate LLM/MCP adapters;
- dedicated clients in the new `GenAI-platform` Keycloak realm;
- self-hosted application, Temporal, and Langfuse persistence;
- read-only MCP tools automatically executed after policy validation, with approval mechanics deferred until sensitive tools enter scope;
- agent status streaming followed by one complete final response;
- initial direct/agent selection only, with model and agent catalogs reserved for later selectors;
- two-user isolation tested and shown in the main demo;
- persistent conversations with no user-facing delete action;
- complete prompt/completion and bounded tool-content capture for synthetic demo data;
- the time MCP server and a versioned 100-card MTG catalog MCP server;
- future support for both trusted and untrusted skills, with capability decisions deferred;
- Linux-only support and a preferred local HTTPS portal origin;
- Apache-2.0/MIT dependencies where feasible, with documented review of exceptions.

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Yandex endpoint/tool-call behavior differs from OpenAI expectations | Agent loop blocked | Phase 0 compatibility spike; adapter and stable model aliases |
| Self-hosted Langfuse makes the local stack heavy | Poor developer experience or host pressure | Permit use of all host resources; pin topology; health checks; measure usage; document selective troubleshooting startup without changing the full-demo contract |
| Temporal history grows with chat/tool payloads | Slow or failed workflows | Store content in app DB; pass references; cap loops/results; continue-as-new if needed |
| Streaming state diverges from durable state | Duplicate/missing UI output | Persist ordered events; replay by sequence; idempotent projection |
| Prompt injection induces unsafe tool requests | Unauthorized action | Tool policy outside prompts; allowlists; read-only classification; schemas; least privilege |
| Keycloak local TLS/issuer is unreachable in containers | Authentication failures | Preserve canonical issuer, trust CA, test split browser/container routing in Phase 0 |
| Observability leaks credentials or user content | Security/privacy exposure | Central redaction, pseudonymous IDs, configurable content capture, retention policy |
| Future scripts weaken the platform boundary | Host compromise/data loss | Separate sandbox service, deny-by-default capabilities, immutable reviewed skills |
| MTG catalog content or pricing lacks clear provenance | Legal ambiguity or misleading demo output | Use a documented permitted source, attribution, dated static prices, and no valuation claims |
| A required transitive service uses a non-preferred license | License-policy mismatch | Inventory pinned images/packages; prefer officially compatible permissive alternatives; explicitly approve unavoidable exceptions |

## 17. Definition of done for the planning stage

Planning is complete when:

- the blocking questions have recorded answers;
- architecture decisions AD-01 through AD-19 are accepted or revised;
- the selected Yandex/Bifrost contract and self-hosted Langfuse topology are verified and documented;
- the two demo MCP use cases are agreed;
- acceptance criteria and delivery phases match the intended demonstration;
- every implementation phase has an agreed runnable handoff, demonstration, evidence, and user-review gate;
- this document is approved as the baseline for implementation estimates and task breakdown.

## 18. Reference documentation

- [Bifrost supported providers and OpenAI-compatible response format](https://docs.getbifrost.ai/providers/supported-providers/overview)
- [Bifrost custom providers](https://docs.getbifrost.ai/providers/custom-providers)
- [Bifrost MCP agent mode](https://docs.getbifrost.ai/mcp/agent-mode)
- [Langfuse observability SDK overview](https://langfuse.com/docs/observability/sdk/overview)
- [Langfuse data model](https://langfuse.com/docs/observability/data-model)
- [Langfuse official self-hosted Docker Compose topology](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml)
- [Bifrost repository and Apache-2.0 license](https://github.com/maximhq/bifrost)
- [Temporal repository and MIT license](https://github.com/temporalio/temporal)
- [Keycloak repository and Apache-2.0 license](https://github.com/keycloak/keycloak)
- [Yandex Cloud text generation REST API](https://yandex.cloud/en/docs/foundation-models/text-generation/api-ref/)
- Local reference: `/home/dvy/Projects/mcpcontext-demo/docs/decisions/0007-yandex-openai-compatibility.md`
