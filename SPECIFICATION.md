# Porfirium specification

Status: current as-built contract

## Purpose

Porfirium demonstrates a multi-user, locally deployed agent platform with authenticated chat,
durable execution, policy-controlled tools, immutable agent releases, portal authoring, and
observable model/tool activity.

## Product behavior

- Users authenticate through Keycloak using Authorization Code with PKCE.
- The portal offers persistent Direct and Agent conversations.
- Direct mode streams a model response through the Portal API and Agentgateway.
- Agent mode executes a selected immutable release through Temporal and persists ordered status,
  tool, and final-response events.
- Users can reconnect to an in-progress turn without starting duplicate work.
- Conversations, drafts, test sessions, releases, and audit data are owner-scoped unless an
  explicit privileged operation requires broader access.
- Authorized authors can create, revise, validate, and privately test declarative agents.
- Separately authorized publishers can publish and deprecate releases.
- Operators can validate and publish repository agent packages with the `porfirium` CLI.

## System boundaries

The browser calls only the Portal API through the same-origin TLS endpoint. It never calls
Temporal, Agentgateway, an MCP server, Langfuse, a database, or Yandex Cloud directly.

The Portal API owns authentication, authorization, conversation persistence, catalog selection,
authoring, publication, and streaming. Temporal workflows own deterministic orchestration;
activities perform database, model, tool, and tracing I/O. Agentgateway is the only model and MCP
gateway. PostgreSQL stores product state independently of Temporal history. Langfuse receives
observability data and is not a source of product truth.

See [Architecture](docs/ARCHITECTURE.md) for component relationships and trust boundaries.

## Agent release contract

An agent release has a stable agent ID, semantic version, schema version, display metadata,
instructions, model alias, reviewed tool declarations, and behavioral limits. Its canonical
artifact and digest cover every execution-relevant field.

Publication is atomic and immutable:

- the same identity and identical content is idempotent;
- changed content under an existing version is rejected;
- publication does not change the default release;
- deprecation blocks new selection but does not alter accepted work;
- runtime execution uses persisted artifacts and snapshots, not a mutable source directory;
- changes require a new semantic version.

Each accepted Agent turn stores a self-contained snapshot containing the exact release identity
and digest, model target, instructions, reviewed tool definitions and grants, and execution limits.
Retries and recovery reuse that snapshot without consulting mutable defaults or catalogs.

## Durable execution

`AgentRunWorkflow` executes declarative agents on `porfirium-agent-runtime-v1`. Workflow code must
remain deterministic. External calls and persistence occur in activities with bounded retries,
timeouts, and idempotency.

A turn has exactly one terminal outcome. The application persists ordered events and one atomic
assistant response. Cancellation and worker restart must not create a second accepted turn,
snapshot, tool side effect, or final answer.

## Model and tool access

Application adapters call Agentgateway for model inference and MCP execution. Provider-specific
wire behavior stays behind those adapters. The platform database remains authoritative for
conversation history; provider response IDs may be stored only as trace metadata.

Tool access is deny-by-default. Before every call, the application validates the exact tool name,
enabled state, grant, JSON schema, arguments, result size, call count, and read-only policy.
Agentgateway authorization is defense in depth, not the primary policy boundary. Only explicit
reviewed tool definitions are sent to the model.

Current demo tools provide time lookup and a dated MTG catalog snapshot. Catalog prices are not
live quotes. Data provenance is documented in
[the catalog data notes](services/mtg-catalog-mcp/data/README.md).

## Identity and authorization

The Portal API validates Keycloak JWTs locally using cached JWKS and enforces issuer, audience,
expiry, roles, ownership, and resource state server-side. Browser bearer tokens and
browser-controlled user identifiers are never forwarded to internal services.

Roles used by the current platform are:

- `genai-user` for ordinary portal use;
- `genai-agent-author` for owned drafts, revisions, validation, and private tests;
- `genai-agent-publisher` for publication and deprecation;
- `genai-admin` for administrative access where explicitly implemented.

Roles do not imply one another unless the API explicitly defines that relationship.

## Persistence and isolation

Product state lives in PostgreSQL with foreign keys and uniqueness constraints supporting owner
isolation, idempotency, version immutability, and ordered events. Temporal history supports durable
orchestration but is not the query model for the portal.

Every user-controlled prompt, manifest field, tool argument, tool result, provider payload, and
artifact is untrusted input. Responses and diagnostics must be bounded before persistence or
streaming. Secrets and credentials must not appear in source control, agent manifests, prompts,
events, logs, traces, or artifacts.

## Observability

The accepted turn correlation ID is propagated as the W3C trace ID across application, model, and
tool calls. Langfuse records model generations and application observations. Logs, persisted
events, audits, and traces must use stable identifiers and redact credentials and bearer tokens.
Observability failure must not corrupt product state.

## Deployment

The supported development topology is Docker Compose on Linux. `compose.yaml` and `deploy/` own
runtime configuration. External images are pinned by digest where practical. Internal services
remain on private Compose networks unless a documented operator interface requires a localhost
binding.

Configuration and secrets are supplied through environment variables. `.env`, tokens, provider
payloads, and production data must never be committed.

## Verification requirements

Every defect fix requires a regression test. Changes to authorization, persistence, publication,
workflow behavior, isolation, or migrations require explicit tests for both allowed and rejected
paths. Use narrow backend or frontend suites while developing, then run the relevant repository
verification scripts.

The main current gates are:

```bash
./scripts/phase4/verify.sh
./scripts/increment8/verify.sh
./scripts/increment9/verify.sh
```

Live provider checks are deliberate operations because they require credentials, external state,
and may incur cost. Operational procedures are in [Operations](docs/OPERATIONS.md).

## Deferred scope

The current runtime supports declarative agents only. Executable third-party agent code, arbitrary
images or dependencies, write-capable tools, delegated user credentials, approval UI, live price
feeds, multi-host scheduling, and production Kubernetes deployment are outside the as-built
contract. The bounded executable-agent proposal is documented separately in
[Executable agent isolation](docs/architecture/INCREMENT10_PLAN.md).
