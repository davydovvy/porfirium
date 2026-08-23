# Agentgateway and Versioned Agent Platform Transition Plan

Status: In progress — Increments 0–8 and Milestones M1–M3 accepted; Increment 9 implementation candidate awaiting acceptance

Last updated: 2026-08-23
Starting point: Phases 0–4 implemented and accepted

Acceptance evidence is maintained in [Architecture Transition Results](TRANSITION_RESULTS.md).

## 1. Purpose

This plan defines two coordinated architectural changes:

1. replace Bifrost's LLM and MCP gateway roles with Agentgateway; and
2. separate agent definitions and versions from the Porfirium platform so agents can be developed independently, published from a source directory, or created through the portal.

The changes are intentionally delivered through independently reversible increments. The platform must remain runnable and testable after every increment. Existing Phase 0–4 documents remain evidence for the implemented Bifrost-era baseline; this document defines the target architecture and the transition away from that baseline.

## 2. Outcomes

The transition is complete when:

- all Yandex LLM traffic and all MCP traffic pass through a pinned Agentgateway deployment;
- no application code depends on Agentgateway-specific request headers or wire formats outside gateway adapters;
- Direct mode retains semantic SSE streaming and persisted conversations;
- Agent mode retains Temporal durability, cancellation, policy enforcement, tool audit events, and Langfuse correlation;
- agents are cataloged and selected by stable identity and immutable version;
- a published run is pinned to an exact agent version, artifact digest, model configuration, and tool-policy snapshot;
- new agent versions can be published without changing or rebuilding the Portal API or the platform-owned Temporal workflow;
- filesystem and portal publication use the same validation and release pipeline; and
- independently supplied executable code runs outside the Portal API and orchestration worker trust boundary.

## 3. Architectural principles

1. **Preserve behavior before replacing infrastructure.** Capture the accepted behavior in executable tests before either gateway is changed.
2. **Use ports at platform boundaries.** The application depends on `ModelGateway`, `ToolGateway`, `AgentCatalog`, and `AgentRuntime` contracts rather than vendor APIs.
3. **Keep authorization in the platform.** Agentgateway authorization is defense in depth. It does not replace the platform's user, agent, tool, argument, and policy checks.
4. **Publish immutable versions.** A published `(agent_id, version)` cannot be overwritten with different content.
5. **Pin every run.** Active runs never resolve `latest` dynamically.
6. **Keep orchestration platform-owned.** Ordinary agents use a generic, deterministic Temporal workflow. Agent packages do not register arbitrary workflow implementations.
7. **Separate control and execution planes.** Authoring, validation, and publication do not execute agent code inside the Portal API.
8. **Treat copied source as an input, not a live deployment.** Publication produces a validated, immutable artifact before a version becomes selectable.
9. **Retain standard protocols.** LLM calls use the OpenAI Responses contract; tool discovery and execution use MCP; tracing uses W3C trace context and OpenTelemetry.

## 4. Target system context

```text
                              Control plane

    Filesystem / CLI ─┐
                      ├──► Agent publisher ──► Agent catalog / artifacts
    Portal editor ────┘          │                       │
                                 └── validate/publish ───┘

                              Execution plane

    Browser ──► Portal API ──► Generic Temporal workflow
                    │                    │
                    │                    ▼
                    │              Agent runtime
                    │               │         │
                    ▼               ▼         ▼
             Application DB    ModelGateway ToolGateway
                                      │         │
                                      └────┬────┘
                                           ▼
                                     Agentgateway
                                      │         │
                                      ▼         ▼
                                   Yandex    MCP servers

    Portal API, workers, runners, and Agentgateway export correlated telemetry
    through OpenTelemetry to Langfuse.
```

Agentgateway may expose its LLM and MCP surfaces on one process, but the platform treats them as distinct logical trust boundaries with separate adapters, configuration, timeouts, and tests.

## 5. Clean component boundaries

The desired code organization is:

```text
apps/portal-api/
  api/                       # HTTP controllers and schemas
  application/               # use cases and transaction boundaries
  domain/                    # entities, policies, and invariants
  ports/                     # dependency interfaces
  adapters/
    persistence/
    temporal/
    agentgateway/
    filesystem_catalog/

services/agent-orchestrator/
  workflows/                 # deterministic, platform-owned workflows
  activities/                # I/O boundaries and durable operations

services/agent-runner/
  runtime/
    declarative/
    python/
  sandbox/

packages/contracts/
  agent_manifest/
  agent_runtime/
  events/
  gateway/

agents/
  <agent-name>/
    <version>/
```

The first refactoring may keep these modules in the existing Portal API image. Physical service separation follows only when contracts and tests are stable.

### 5.1 Required ports

```python
class ModelGateway:
    async def respond(self, request: ModelRequest) -> ModelResponse: ...
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...

class ToolGateway:
    async def list_tools(self, context: ToolContext) -> list[ToolDefinition]: ...
    async def call_tool(self, context: ToolContext, call: ToolCall) -> ToolResult: ...

class AgentCatalog:
    async def resolve(self, agent_id: str, version: str) -> AgentRelease: ...
    async def publish(self, candidate: AgentCandidate) -> AgentRelease: ...

class AgentRuntime:
    async def next_step(self, context: RunContext) -> AgentStep: ...
```

Vendor-specific model names, MCP name prefixes, headers, error envelopes, and session handling belong in adapters. Domain and application code use stable platform identifiers.

## 6. Agent package and release contract

### 6.1 Directory layout

```text
agents/
  tool-assistant/
    1.0.0/
      agent.yaml
      prompts/
        system.md
      src/
        agent.py
      tests/
      pyproject.toml
      uv.lock
      README.md
```

Declarative agents may omit `src`, `pyproject.toml`, and `uv.lock`. A portal-created declarative agent produces the same canonical manifest and artifact as an equivalent filesystem package.

### 6.2 Manifest

```yaml
apiVersion: porfirium.ai/v1alpha1
kind: Agent

metadata:
  name: tool-assistant
  version: 1.0.0
  displayName: Tool Assistant
  description: Uses approved time and MTG catalog tools.

runtime:
  type: python
  entrypoint: src.agent:Agent
  contractVersion: "1"

model:
  alias: default
  parameters:
    maxOutputTokens: 2048

execution:
  maxIterations: 4
  timeoutSeconds: 300
  maxToolCalls: 12
  maxToolResultBytes: 65536

tools:
  - server: demo-time
    names: [get_current_time, convert_time]
    access: read-only
  - server: demo-mtg-catalog
    names: [search_cards, get_card, compare_cards, list_sets]
    access: read-only

prompts:
  system: prompts/system.md

permissions:
  network: gateway-only
  filesystem: none
  secrets: []
```

The manifest schema is versioned independently of individual agents. Unknown fields fail validation until the schema explicitly permits forward-compatible extensions.

### 6.3 Publication pipeline

Both publication paths invoke one application service:

```text
candidate source or portal draft
             │
             ▼
manifest/schema validation
             │
             ▼
tool, model, policy, and permission resolution
             │
             ▼
tests, dependency lock checks, and security checks
             │
             ▼
canonical package + content digest
             │
             ▼
immutable artifact build/store
             │
             ▼
AgentVersion record becomes published
```

Copying files into `agents/` does not make an agent immediately runnable. Publication must read from a completed staging directory and commit the catalog record atomically. A changed package must use a new version. Removing the source directory must not invalidate an already published artifact.

### 6.4 Portal authoring scope

The first portal builder supports declarative agents:

- metadata and prompts;
- model alias and allowed parameters;
- reviewed tool selection;
- execution limits;
- draft validation;
- a controlled test conversation;
- publish and deprecate operations.

Arbitrary source editing or archive upload is deferred until an isolated build and execution path exists. When introduced, it is administrator-only by default and never imports user code into the Portal API or shared Temporal worker.

## 7. Generic durable agent execution

The platform replaces agent-specific Temporal workflow classes with one stable workflow for ordinary agents:

```text
AgentRunWorkflow
  1. load the immutable run snapshot;
  2. ask the selected AgentRuntime for the next step;
  3. persist and return a final response, or;
  4. authorize every proposed tool call;
  5. execute allowed calls through ToolGateway;
  6. record bounded results and continue;
  7. enforce cancellation, iteration, time, token, call, and size limits.
```

Workflow input contains references rather than mutable definitions or large payloads:

```text
run_id
turn_id
agent_version_id
agent_artifact_digest
model_configuration_snapshot_id
tool_policy_snapshot_id
trace_context
```

The workflow never resolves the latest agent version after the run starts. Activity names and workflow types remain platform-owned. Changes that affect replay use Temporal worker versioning or a new workflow type/task queue.

## 8. Persistence changes

Add the following records:

| Record | Purpose |
|---|---|
| `agents` | Stable agent identity, ownership, visibility, and metadata. |
| `agent_versions` | Immutable version, digest, manifest, artifact, runtime, and lifecycle state. |
| `agent_drafts` | Mutable portal-authored configuration before publication. |
| `agent_publications` | Validation/build attempts, results, and provenance. |
| `model_aliases` | Stable platform alias mapped to an Agentgateway model route. |
| `tool_catalog_entries` | Stable platform tool identity mapped to an MCP target and exposed name. |
| `agent_tool_grants` | Reviewed tool permissions for one agent version. |
| `agent_runs` | Run projection and all pinned snapshot identifiers. |

Modify conversations to reference an agent identity and version selection. Pin the resolved `agent_version_id` on every run. Existing conversations do not silently upgrade; upgrading a conversation to another published version is explicit and auditable.

Existing `tool_requests` should reference `agent_version_id` and stable tool-catalog identity while retaining the external gateway name as execution evidence.

## 9. Transition increments

### Increment 0 — Freeze accepted behavior

Implementation: [Migration Regression Gate](MIGRATION_REGRESSION_GATE.md)

Status: **Completed and accepted on 2026-08-21.** The complete live migration-baseline command passed against the Bifrost Phase 0–4 deployment, including paid Yandex compatibility checks and controlled service-restart recovery.

Build a non-regression suite covering:

- Direct Responses requests and semantic SSE streaming;
- strict structured output;
- no-tool, single-tool, and multi-tool Agent turns;
- forced tool selection and stateless function-result continuation;
- malformed, oversized, unknown, and denied tool calls;
- persisted tool audit events;
- cancellation and Temporal worker restart recovery;
- gateway and MCP-server restart recovery;
- token usage and Langfuse trace correlation; and
- cross-user conversation, event, cancellation, and audit isolation.

**Exit gate:** the complete suite passes through the existing Bifrost deployment.

### Increment 1 — Introduce vendor-neutral gateway adapters

Status: **Completed and accepted on 2026-08-21.** `ModelGateway` and `ToolGateway` contracts and Bifrost adapters are in place. Direct and Agent execution use the ports, and focused adapter tests cover request/response normalization, semantic SSE events, tool discovery/execution, bounds, tracing headers, provider selection, and normalized upstream failures. The complete live migration regression gate passed after the refactoring.

- Extract all model calls from the Portal API and worker into `ModelGateway`.
- Extract MCP discovery and execution into `ToolGateway`.
- Define normalized request, stream event, response, usage, tool, and error contracts.
- Keep Bifrost as the active implementation.
- Prohibit direct Bifrost URLs, `x-bf-*` headers, and Bifrost response parsing outside its adapters.

**Exit gate:** existing acceptance tests pass and application/domain code contains no Bifrost wire-contract dependencies.

### Increment 2 — Agentgateway/Yandex compatibility spike

Status: **Completed and accepted on 2026-08-21.** Agentgateway 1.4.0 is pinned by digest and runs side by side on port 8089 while Bifrost remains active. `./scripts/agentgateway-spike/verify.sh` proves the model, MCP, authorization, trace, and restart contracts. See [Architecture Transition Results](TRANSITION_RESULTS.md) for evidence and integration findings.

Run Agentgateway beside Bifrost and pin its image by digest. Configure:

- a custom Yandex provider with explicit Responses and Chat Completions paths;
- a stable platform model alias;
- provider authentication, timeout, and bounded retry behavior;
- OpenTelemetry export to Langfuse;
- the diagnostic, time, and MTG Streamable HTTP MCP targets;
- deterministic MCP tool-prefix behavior; and
- deny-by-default MCP authorization.

Repeat the paid Phase 0 compatibility checks: non-streaming Responses, semantic SSE, strict JSON Schema, forced function call, MCP execution, stateless continuation, usage reporting, tracing, and restart recovery.

**Exit gate:** every contract passes against the pinned Agentgateway/Yandex combination. Configuration support alone is not sufficient.

### Increment 3 — Cut MCP traffic over

Status: **Completed and accepted on 2026-08-22.** Agentgateway is the default MCP provider through `AgentgatewayToolGateway`. Model traffic remains on the accepted Bifrost `ModelGateway`, and `TOOL_GATEWAY_PROVIDER=bifrost` remains the configuration-only rollback.

- Implement standard MCP initialize/session handling, `tools/list`, and `tools/call` in `AgentgatewayToolGateway`.
- Normalize JSON-RPC errors and tool-result envelopes.
- Establish a stable mapping from platform tool IDs to Agentgateway target/tool names.
- Propagate W3C trace context.
- Keep platform authorization authoritative and add Agentgateway CEL rules as defense in depth.
- Add focused adapter tests for discovery, execution, denial, malformed responses, response bounds, upstream failures, and trace propagation.
- First exercise the complete application with `TOOL_GATEWAY_PROVIDER=agentgateway` as an explicit canary while retaining Bifrost for immediate rollback.
- Run the Agentgateway spike gate and complete migration regression gate before changing the default provider.
- Make Agentgateway the default MCP provider only after all gates pass; rollback remains the configuration-only change `TOOL_GATEWAY_PROVIDER=bifrost`.

**Exit gate:** focused adapter tests, `./scripts/agentgateway-spike/verify.sh`, and `./scripts/migration-baseline/verify.sh` pass with Agentgateway selected for MCP. Tool discovery, execution, denial, audit, restart recovery, and trace correlation must remain equivalent to the accepted baseline. No Bifrost MCP path is removed in this increment.

### Increment 4 — Cut LLM traffic over

Status: **Completed and accepted on 2026-08-22.** Agentgateway is the default model provider through `AgentgatewayModelGateway`; `MODEL_GATEWAY_PROVIDER=bifrost` remains the configuration-only rollback.

- Implement non-streaming and streaming Responses calls in `AgentgatewayModelGateway`.
- Supply approved tool definitions explicitly in model requests.
- Normalize Responses events, function calls, structured output, usage, and errors.
- Preserve stateless `function_call_output` continuation.
- Propagate the existing turn trace as standard W3C trace context.
- Switch with `MODEL_GATEWAY_PROVIDER=agentgateway` while retaining Bifrost for rollback.

Use controlled synthetic canaries rather than duplicating ordinary user prompts to both paid gateways.

**Exit gate:** Direct and Agent modes pass the complete acceptance suite.

### Increment 5 — Retire Bifrost

Status: **Completed and accepted on 2026-08-22.** Current operation, application adapters, Compose, and verification no longer contain Bifrost; the old unreferenced local volume was deliberately not deleted.

- Remove the Bifrost service, configuration, dependencies, environment variables, scripts, and documentation references from current operational paths.
- Replace Bifrost health and discovery checks with Agentgateway checks.
- Update image/license evidence and the runbook.
- Keep removal of the persistent Bifrost volume as a separate, explicit destructive operation.

**Exit gate:** a clean checkout starts, verifies, and operates without a Bifrost image or volume.

### Increment 6 — Add the versioned agent catalog

Status: **Completed and accepted on 2026-08-23.** The bundled `tool-assistant:1.0.0` release now pins immutable run snapshots and preserves the Phase 4 behavior under the complete live verification suite.

- Add catalog, draft, publication, model-alias, tool-catalog, grant, and run-snapshot migrations.
- Implement manifest validation and immutable version/digest rules.
- Package the existing `tool_assistant_v1` behavior as the first published agent.
- Resolve and pin an `AgentVersion` when a run is accepted.
- Expose read-only catalog APIs and add an agent selector to conversation creation.

**Exit gate:** existing Agent behavior runs through a pinned catalog version without changing its visible behavior.

### Increment 6.5 — Retire the legacy Temporal runtime

Focused implementation plan: [Increment 6.5 — Legacy Temporal runtime retirement plan](INCREMENT6_5_LEGACY_RUNTIME_RETIREMENT_PLAN.md).

Status: **Implemented on 2026-08-23.** Its bounded maintenance interval ended when Increment 7 reopened generic-runtime admission. See [Increment 6.5 results](INCREMENT6_5_RESULTS.md).

- Close admission for new Agent turns before changing the execution plane.
- Reconcile and drain all open V1/V2 workflows and active application turns.
- Remove the legacy worker, `porfirium-agent-v1` queue configuration, and production start/registration paths.
- Preserve completed histories, immutable releases, snapshots, events, and audits without a live compatibility poller.
- Keep Direct mode and read-only historical Agent views available during the bounded maintenance interval.

**Exit gate:** no open legacy execution or active Agent turn remains; no deployed worker polls the legacy queue; Agent admission fails cleanly without partial persistence; the remaining platform and historical data pass retirement verification.

### Increment 7 — Introduce the generic Temporal workflow

Focused implementation plan: [Increment 7 — Generic versioned agent runtime plan](INCREMENT7_PLAN.md).

Status: **Completed and accepted on 2026-08-23.** See [Increment 7 results](INCREMENT7_RESULTS.md).

- Add `AgentRunWorkflow` and version-neutral activities.
- Move prompts, limits, model selection, and tool grants out of worker constants into the pinned release/snapshots.
- Start all new Agent runs on the generic runtime task queue.
- Re-enable Agent admission only after the generic worker is healthy.
- Use Temporal-compatible workflow/worker versioning for future changes.

**Exit gate:** two agent versions can run through the generic workflow; an active run survives worker restart and publication of a newer agent version; no legacy worker or queue is reintroduced.

### Increment 8 — Add filesystem/CLI publication

Focused implementation plan: [Increment 8 — Filesystem and CLI publication plan](INCREMENT8_PLAN.md).

Status: **Completed and accepted on 2026-08-23.** See
[Increment 8 results](INCREMENT8_RESULTS.md).

Provide commands equivalent to:

```text
porfirium agents validate agents/tool-assistant/1.3.0
porfirium agents publish agents/tool-assistant/1.3.0
porfirium agents status tool-assistant:1.3.0
```

An optional local scanner may detect candidates, but it must publish only complete, validated staging directories. The runner must use the immutable artifact, not a mutable bind mount.

**Exit gate:** a new independently developed version can be copied, validated, published, selected, executed, and rolled back without rebuilding the Portal API.

### Increment 9 — Add the portal agent builder

Focused implementation plan: [Increment 9 — Portal declarative agent builder plan](INCREMENT9_PLAN.md).

Status: **Implemented candidate; live role and user acceptance pending.**

Implementation evidence: [Increment 9 results](INCREMENT9_RESULTS.md).

- Add draft create/edit/validate/test/publish/deprecate flows.
- Apply administrator/author roles separately from ordinary agent-use permissions.
- Use the same publisher and manifest contracts as filesystem publication.
- Make publication errors visible without making an invalid draft selectable.
- Record author, provenance, digest, validation result, and publication timestamp.

**Exit gate:** a declarative portal-created agent and an equivalent filesystem agent produce the same release contract and execution behavior.

### Increment 10 — Isolate executable agent code

- Build or store a locked immutable artifact for each executable agent version.
- Run code as non-root with a read-only filesystem and without host mounts or a Docker socket.
- Do not provide platform database, Yandex, or MCP credentials to agent code.
- Restrict egress to approved platform interfaces.
- Enforce CPU, memory, elapsed-time, token, tool-call, and output limits.
- Grant secrets by explicit name and scope only when the runtime supports secure delivery.
- Separate runner pools or Temporal task queues by runtime and trust class.

**Exit gate:** executable code can fail, time out, or behave maliciously without compromising the Portal API, orchestration worker, gateway credentials, or another run.

## 10. Proposed API evolution

```text
GET    /api/v1/agents
GET    /api/v1/agents/{agent_id}
GET    /api/v1/agents/{agent_id}/versions
GET    /api/v1/agents/{agent_id}/versions/{version}

POST   /api/v1/agent-drafts
GET    /api/v1/agent-drafts/{draft_id}
PATCH  /api/v1/agent-drafts/{draft_id}
POST   /api/v1/agent-drafts/{draft_id}/validate
POST   /api/v1/agent-drafts/{draft_id}/test
POST   /api/v1/agent-drafts/{draft_id}/publish

POST   /api/v1/agent-imports
GET    /api/v1/agent-publications/{publication_id}

POST   /api/v1/conversations
POST   /api/v1/conversations/{conversation_id}/agent-version
```

Conversation creation accepts either Direct mode plus a model alias, or Agent mode plus a published agent identity/version. The server remains responsible for resolving authorization and defaults.

## 11. Rollout and rollback rules

- LLM and MCP providers use separate feature switches so either cutover can be reverted independently.
- Database migrations are additive until all old application versions are retired.
- New writes populate both legacy and new projection fields only for a bounded compatibility period.
- Legacy Temporal workflow/activity registrations remain deployed until a reconciled drain proves that no open execution requires them; Increment 6.5 then removes their live workers and queues before the generic runtime is introduced.
- A failed publication never updates the active/default agent version.
- Deprecation prevents new selection but does not delete artifacts required by historical runs.
- Gateway rollback never changes the run's agent or policy snapshot.
- Persistent volume deletion, artifact deletion, and published-version deletion are not part of normal rollback.

## 12. Security boundaries

- Browser tokens terminate at the Portal API and are not forwarded unchanged to Yandex or MCP servers.
- Portal roles distinguish agent use, agent authoring, and agent publication.
- Agentgateway authenticates platform callers and applies least-privilege LLM/MCP policies.
- MCP tool authorization checks user, agent version, stable tool identity, arguments, schema version, and policy snapshot before every call.
- Tool discovery does not grant execution rights.
- Agent packages cannot declare permissions beyond those the publisher is authorized to grant.
- Prompts, code, tool arguments, and tool results are treated as untrusted input.
- Secrets, bearer tokens, cookies, and provider credentials are prohibited from manifests, artifacts, events, Temporal histories, and trace payloads.

## 13. Observability

The turn correlation ID remains the logical trace ID. Propagate `traceparent` through the Portal API, Temporal headers, Agent runtime, Agentgateway LLM requests, Agentgateway MCP calls, and downstream services.

Required observations include:

- agent identity, version, and artifact digest;
- run, turn, conversation, workflow, and pseudonymous user references;
- model alias, resolved provider/model, latency, usage, and outcome;
- stable tool ID, target, external name, policy version, decision, latency, and outcome;
- publication validation/build stages and errors; and
- bounded synthetic prompts, outputs, arguments, and results under the existing privacy rules.

Replacing Bifrost's `x-bf-session-id` behavior must not break Langfuse trace lookup by turn correlation ID.

## 14. Delivery milestones

| Milestone | Included increments | User-visible result |
|---|---|---|
| M1 — Gateway seam and proof | 0–2 | Complete; Agentgateway/Yandex compatibility is proven. |
| M2 — Agentgateway production cutover | 3–5 | Complete; LLM and MCP traffic use Agentgateway and Bifrost is removed. |
| M3 — Versioned agent runtime | 6–7 | Complete; conversations select immutable agent versions executed by a generic durable workflow. |
| M4 — Independent publication | 8–9 | Agents can be published from directories or created declaratively in the portal. |
| M5 — Executable-code isolation | 10 | Independently supplied code runs in a constrained runner boundary. |

No milestone combines a gateway cutover with a database/catalog or Temporal workflow migration.

Current progress: Increments 0–8 and Milestones M1–M3 are complete and accepted. Increment 6.5 retired the legacy runtime; Increment 7 runs immutable declarative releases through the generic workflow with Agent admission reopened. Increment 8 publishes immutable declarative releases from version directories through the shared publisher and CLI. The filesystem-published `tool-assistant:1.3.0` release was accepted through the portal. Increment 9 is implemented as a candidate and awaits live role/user acceptance, so Milestone M4 remains open.

## 15. Deferred decisions

The following decisions require a focused design or spike before their increment begins:

- the exact pinned Agentgateway version and standalone configuration schema;
- Agentgateway MCP prefix mode and stable tool-name mapping;
- artifact storage for local Compose and later non-local deployments;
- OCI-per-version versus locked-package runner artifacts;
- signing and provenance format;
- declarative agent graph/schema beyond the initial bounded tool loop;
- portal source-code editing or upload;
- sandbox implementation and supported language runtimes;
- agent version retention and administrative deletion policy; and
- how user-delegated MCP credentials are exchanged and scoped.

These decisions must not weaken the immutable-version, pinned-run, application-authorization, or isolated-execution requirements above.
