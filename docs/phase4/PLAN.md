# Porfirium Phase 4 implementation plan

Status: Implemented and accepted  
Scope: MCP tools and server-side tool policy  
Prerequisite: Phase 3 accepted

## Outcome

Phase 4 turns the durable no-tool Agent increment into a bounded, tool-using agent. An authenticated user can ask for current-time information or query the bundled Magic: The Gathering catalog, observe persisted tool progress in the portal, receive one complete final answer, and inspect the correlated model/tool path. Tool access is decided by application policy on every call; prompting the model cannot expand that access.

The phase is complete when specification acceptance criteria 4, 7, and 8 pass:

- an Agent turn durably invokes at least one MCP tool and returns a final answer;
- restarting the Temporal worker does not lose an accepted run, including a run with tool activity;
- unavailable, unknown, malformed, or non-allowlisted tools fail closed even when explicitly requested in a prompt.

## Scope boundaries

Included:

- two independently packaged, read-only MCP servers;
- a checked-in, versioned 100-card MTG dataset and its attribution/refresh documentation;
- explicit, versioned Agent tool policy and policy snapshots;
- an application-controlled model/tool loop in Temporal activities;
- persisted tool audit records and replayable tool-status events;
- correlated Langfuse observations for model requests and tool executions;
- portal rendering for tool requests, execution, results, and denials;
- automated policy, durability, isolation, and live tool smoke tests;
- Phase 4 start, stop, status, verification, runbook, and results evidence.

Deferred:

- tools with side effects and interactive approval UI;
- live MTG prices, arbitrary network retrieval, RAG, embeddings, and card-image hosting;
- user-defined tools, agents, or policies;
- Phase 5's broader dependency-failure matrix, load limits, and demo hardening except for limits required to make the Phase 4 tool loop safe.

## Fixed design decisions

1. The Python worker owns the tool loop. Bifrost automatic MCP tool execution remains disabled.
2. Bifrost is used through separate LLM and MCP adapters even though both interfaces share one deployment.
3. Every model-proposed tool call is untrusted until the backend validates the stored user, agent/version, exact external tool name, arguments, environment allowlist, and configured read-only classification.
4. Policy is configuration controlled and versioned. Tool descriptions and prompt text never grant authority.
5. Reviewed read-only tools execute automatically after a successful policy decision. The data model reserves a decision state for future approval-required tools, but Phase 4 adds no approval endpoint behavior or UI.
6. Workflow code only orchestrates bounded references and state. Model calls, policy/audit persistence, and MCP execution remain activities.
7. Existing `PorfiriumAgentWorkflowV1` histories remain replayable. Tool-capable runs use a new workflow definition and task-queue/version identifier rather than changing V1 semantics in place.
8. Tool arguments and results are bounded before persistence, Temporal return, SSE emission, logging, and tracing. Secrets and browser bearer tokens never enter any of those channels.
9. Agent turns continue to emit no partial assistant tokens. They finish with one atomically persisted assistant message.

## Target tool surface

### Time server

Service: `demo-time-mcp`

- `get_current_time(timezone)` returns an ISO 8601 timestamp, canonical timezone, and UTC offset.
- `convert_time(timestamp, from_timezone, to_timezone)` converts an explicit timestamp between IANA timezones.

The implementation uses the packaged timezone database, rejects unknown zones and ambiguous input, performs no network access, and returns structured errors.

### MTG catalog server

Service: `demo-mtg-catalog-mcp`

- `search_cards(query, set_code?, colors?, card_type?, rarity?, min_price?, max_price?, limit?)`;
- `get_card(card_id)`;
- `list_sets()`.

The checked-in dataset contains exactly 20 curated cards from each of `M11`, `ISD`, `RTR`, `THS`, and `KTK`. Generate random number as available quantity at store for each card from 1 to 100. Prices are just random seeded numbers from 0.01 USD to 100 USD. The service performs no arbitrary URL fetches or filesystem access outside its packaged data.

## Data and contracts

Add an application migration for a `tool_requests` audit table with, at minimum:

- immutable request ID, turn ID, owner ID, run/workflow ID, and model call ID;
- agent name/version and policy version/snapshot reference;
- MCP server, internal tool identity, exact Bifrost-exposed name, and schema version;
- bounded arguments plus validation outcome;
- decision (`allowed`, `denied`, or reserved `approval_required`) and reason code;
- execution state, bounded result or error reference, timing, and correlation identifiers;
- idempotency key derived from turn, loop iteration, and model tool-call ID;
- created, started, and completed timestamps.

Database constraints must prevent duplicate execution/audit rows for the same logical call. Owner-scoped joins must preserve the existing cross-user isolation model.

Define typed internal contracts rather than passing provider payloads through the workflow:

- `ToolDefinition` and bounded JSON Schema;
- `ToolCallRequest` and normalized arguments;
- `PolicySnapshot` and `PolicyDecision` with stable reason codes;
- `ToolExecutionRequest`, with an optional opaque delegated-credential reference, and `ToolExecutionResult`;
- bounded `AgentStepResult` for `final_answer`, `tool_calls`, or a controlled failure.

The initial policy maps `tool_assistant_v1` to the reviewed Phase 4 tools. Diagnostic Phase 0 tools and all unknown tool names are explicitly absent. Startup and verification continue to enforce Bifrost's global deny-by-default automatic-injection setting.

### Future delegated OIDC identity contract

Phase 4's synthetic, read-only MCP services may use private-network or service authentication, but the tool gateway contract must not assume service-only identity. A later user-specific MCP integration must be possible without changing workflow orchestration or tool-policy semantics.

- An execution request may carry an opaque `delegated_credential_ref`; it never carries a bearer token in workflow input, workflow history, database audit data, events, logs, or traces.
- FastAPI remains the browser token boundary: it validates the original Keycloak access token and never forwards browser credentials merely because the model requested a tool.
- The preferred future execution path has Bifrost exchange the user's subject token with Keycloak using OAuth 2.0 Token Exchange (RFC 8693) before calling the MCP server.
- The exchanged token must be short lived and restricted to the selected MCP server's audience and least-privilege scopes. The original portal token must not be forwarded unchanged to MCP servers.
- Bifrost authenticates to Keycloak as a confidential token-exchange client. If the pinned Bifrost version lacks the required RFC 8693 behavior, a dedicated Porfirium token-broker adapter may perform the exchange and provide only the resulting downstream token to Bifrost through an explicitly allowlisted, non-logged header.
- Each MCP server independently validates issuer, audience, expiry, scopes/roles, and relevant delegation or actor claims. A valid token does not replace application tool authorization.
- Application policy answers whether the agent may perform the proposed call; token exchange establishes the delegated identity and downstream authority under which an already-approved call executes. Both checks are required.
- Credential material is resolved only inside the execution activity or gateway, held in memory for the minimum necessary time, excluded from retries and error payloads, and never returned to the model.
- Durable runs use an encrypted credential store or gateway-managed per-user session behind the opaque reference. If delegation cannot be renewed after expiry or restart, the run fails safely with a stable `reauthentication_required` outcome rather than falling back to a service identity.
- Token caching, when introduced, is partitioned by user, target audience, and scope set, expires no later than the exchanged token, and cannot broaden authority across MCP servers or users.

This contract deliberately leaves credential storage and the exact Bifrost extension mechanism for the first user-specific MCP integration, while reserving the required boundary now.

## Durable agent loop

Introduce a new versioned workflow, provisionally `PorfiriumToolAgentWorkflowV2`, with this bounded sequence:

1. Mark the run active and load the stored policy snapshot/reference.
2. Load bounded conversation context in an activity.
3. Request a model response with only policy-approved tool definitions.
4. If the response is final text, persist it atomically and complete the run.
5. For each proposed call, normalize and validate it against the snapshot and tool schema.
6. Persist `tool.requested` and the audit decision before execution.
7. For an allowed read-only call, persist `tool.started`, execute through the MCP adapter with an explicit per-request Bifrost allowlist, then persist a bounded result and `tool.completed`.
8. Append normalized tool outputs to the bounded model context and request the next model step.
9. Repeat until a final answer or a configured iteration/tool/time/result limit is reached.
10. Fail closed with a stable user-safe error for denied calls, malformed calls, exhausted limits, or unavailable dependencies.

Each activity is idempotent and has explicit start-to-close timeouts, bounded retries, and correlation metadata. MCP calls use short timeouts and are not retried when doing so could duplicate an execution unless the call's idempotency contract makes retry safe. Cancellation remains effective between activities and during heartbeat-aware calls. Workflow history stores identifiers and bounded summaries, not full unbounded provider responses.

Initial safety limits should be configuration backed and tested: maximum agent iterations, tool calls per run, tool calls per model response, tool argument bytes, individual and aggregate result bytes, comparison-card count, search limit, model output tokens, and total elapsed time. Exact defaults are selected during implementation and documented in the runbook.

## Events and portal behavior

Persist and replay the specification event vocabulary:

- `agent.status` for planning, model generation, and final synthesis;
- `tool.requested` with a safe tool label and request ID;
- `tool.started` with server/tool identity;
- `tool.completed` with success/failure state and a bounded human-readable summary;
- `turn.completed`, `turn.failed`, or `turn.cancelled` as the terminal event.

Events retain monotonically increasing per-turn sequence numbers and reconnect through the existing SSE path. The portal renders tool steps in order, distinguishes success from denial/failure, does not expose raw internal errors or oversized results, and reconstructs the same state after refresh. Conversation history continues to contain only user and final assistant messages; tool details come from run events/audit projections.

## Observability and security

- Reuse the turn correlation ID as the W3C trace ID and propagate it through Temporal headers, model requests, policy decisions, and MCP calls.
- Record child observations for each model step and MCP execution, including bounded synthetic arguments/results, model/tool versions, latency, usage, outcome, and audit request ID.
- Never trace credentials, access tokens, cookies, database URLs, private keys, or infrastructure secrets.
- Log stable reason codes and correlation identifiers; return non-enumerating, user-safe errors.
- In Phase 4, send no Keycloak bearer token or browser-controlled user identifier to Bifrost or an MCP server. A future delegated integration may disclose a subject token only to the approved exchange component and may send only the resulting audience-restricted token to its target MCP server, as defined above.
- Run both MCP containers as non-root, without host mounts or Docker socket access, on the private Compose network, with health checks and a read-only root filesystem where practical.

## Implementation sequence

### Increment 1 — Contracts, data provenance, and service skeletons

- finalize time tool schemas and MTG dataset selection;
- add the versioned dataset, manifest, checksum, attribution, and refresh documentation;
- create both independently locked MCP services, health endpoints, container builds, and unit tests;
- add Compose services on the private network with non-root/read-only settings;
- add dependency and software/data license evidence before introducing packages or content.

Checkpoint: both services pass unit/schema tests and deterministic direct MCP calls without involving the LLM.

### Increment 2 — Bifrost registration and MCP adapter

- register both clients with pinned names and explicit streamable-HTTP endpoints;
- retain and verify global automatic tool injection is disabled;
- implement a `ToolGateway` adapter for discovery and explicit execution;
- normalize Bifrost errors, enforce time/size bounds, and verify exact exposed names;
- extend startup/readiness/status checks without exposing MCP ports publicly unless a documented debug bind is required.

Checkpoint: verification discovers exactly the reviewed Phase 4 tools and explicitly executes one deterministic call on each server; diagnostic tools remain unavailable to ordinary Agent requests.

### Increment 3 — Policy and audit persistence

- add the `tool_requests` migration and models;
- add a versioned policy document/configuration and startup validation;
- implement exact-name lookup, agent/environment intersection, read-only classification, JSON Schema validation, and stable allow/deny reason codes;
- persist decisions before execution and make audit writes idempotent;
- add unit/integration tests for allowed, unknown, aliased, malformed, oversized, diagnostic, and future approval-required calls.

Checkpoint: policy tests prove prompt/model output cannot authorize a tool and every attempted call produces one durable audit decision.

### Increment 4 — Versioned durable tool loop

- add the V2 workflow and its typed activities while retaining V1 registration for replay safety;
- make model requests expose only the policy snapshot's approved definitions;
- parse Responses API function calls, validate each call, execute through the MCP adapter, submit function results, and obtain the final answer;
- enforce loop/time/tool/token/result limits, cancellation, retries, and idempotency;
- persist final messages and failure states atomically using existing turn semantics.

Checkpoint: deterministic integration tests cover no-tool answers, one tool call, multiple tool calls, denial, malformed calls, MCP failure, cancellation, activity retry, and worker restart between request, audit, execution, and synthesis steps.

### Increment 5 — Events, portal, and traces

- emit persisted `tool.requested`, `tool.started`, and `tool.completed` events;
- render ordered tool progress and safe summaries in the existing Agent view;
- verify refresh/SSE replay produces no duplicated steps;
- add correlated model/tool observations and audit identifiers in Langfuse;
- retain one atomic final assistant response and Direct mode behavior.

Checkpoint: a user can watch and reconnect to a time or catalog run, then locate its workflow, audit row, and correlated trace.

### Increment 6 — Phase verification and handoff

- add `scripts/phase4/{start,stop,status,smoke,verify}` following prior phase conventions;
- run backend lint/tests, frontend lint/component tests/build, Compose validation, secret scanning, MCP unit/contract tests, and live smoke tests;
- add `docs/phase4/RUNBOOK.md` and populate `docs/phase4/RESULTS.md` with reproducible evidence;
- update the root README and specification implementation status only after verification;
- preserve the Phase 3 live regression smoke.

Checkpoint: the complete acceptance matrix passes and the user can repeat the documented demo with both local accounts.

## Test and acceptance matrix

### Automated local tests

- time conversion across ordinary, daylight-saving, ambiguous, and invalid-zone cases;
- MTG search filters, limits, stable ordering, detail lookup, schema validation, and dataset cardinality/checksum;
- policy allow/deny intersection and argument validation;
- duplicate activity/audit execution resistance;
- ordered event persistence and SSE replay;
- V1 replay/worker compatibility and V2 workflow determinism;
- portal tool-state rendering and reconnect behavior;
- secret-pattern and dependency/license checks.

### Live smoke tests

1. Ask for current time in a named timezone; require the time tool, ordered events, final answer, audit row, and correlated trace.
2. Search the MTG catalog, retrieve detail, and answer a static price question; require repeatable structured results.
3. Restart `agent-worker` after a persisted tool event; require the same workflow to finish without duplicate execution or messages.
4. Prompt for Phase 0 diagnostic tools, a fabricated tool, a name-confusion variant, malformed/oversized arguments, and policy override; require denial, no MCP execution, and durable audit evidence.
5. Sign in as both demo users and verify the second user cannot enumerate, read, stream, cancel, retry, or inspect the first user's turns or tool-request identifiers.
6. Run the Phase 3 Direct and no-tool Agent regressions to prove existing behavior remains intact.

The live suite should minimize paid Yandex requests by combining deterministic adapter/policy checks locally and reserving model calls for the essential end-to-end tool-selection cases. The runbook records the expected paid-call count.

## Definition of done

- both MCP services are reproducibly built, healthy, independently testable, and registered with Bifrost;
- all reviewed tools have explicit schemas, versions, read-only classifications, limits, and tests;
- the application, not the model or Bifrost auto-execution, authorizes every call;
- every attempted tool call has a durable, idempotent audit record and ordered replayable events;
- V2 tool runs survive worker restart and complete without duplicate tool execution or final messages;
- denial and prompt-injection tests prove unavailable tools cannot execute;
- time and MTG demonstrations produce repeatable final answers and correlated traces;
- two-user isolation remains enforced for turns, event streams, cancellation, retry, and tool audit data;
- backend, frontend, Compose, secret, regression, and live Phase 4 verification pass;
- the Phase 4 runbook and results evidence are complete and user acceptance is recorded before Phase 5 begins.
