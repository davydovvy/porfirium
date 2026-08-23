# Increment 9 — Portal declarative agent builder plan

Status: Implemented candidate; live role and user acceptance pending
Target milestone: M4 — Independent publication (portal half)
Prerequisite: Increment 8 filesystem/CLI publication accepted

## Outcome

Increment 9 lets an authorized author create and revise a schema-v2 declarative agent in the
portal, validate an immutable revision against current platform state, exercise that exact
revision in a private test conversation, and submit it for publication by an authorized
publisher. Publication uses the Increment 8 application service and creates the same canonical
artifact, release, grants, and audit contract as an equivalent filesystem candidate.

Published releases appear in the existing Agent selector without becoming the default as an
implicit publication side effect. An authorized publisher can deprecate a release to prevent
new selection while existing conversations, accepted runs, snapshots, artifacts, grants,
publication evidence, and Temporal histories remain intact.

This increment supports only structured schema-v2 manifests with
`runtime.kind = "declarative"` and `runtime.contract_version = 1`. It does not add raw JSON or
source-code editing, package/archive upload, dependency installation, executable entrypoints,
new tools or model aliases, approval-required tools, or mutable published releases.

The increment is complete when a portal-created release and a filesystem-created equivalent
produce byte-identical canonical artifacts and equivalent grants, execute through the unchanged
`AgentRunWorkflow`, enforce separate use/author/publish permissions, and preserve safe selection
and run behavior across publication and deprecation.

## Scope

Included:

- author and publisher realm roles enforced independently by the Portal API;
- an owner-scoped draft list and structured create/edit/clone experience;
- immutable draft revision identities for validation, testing, and publication;
- server-derived model and reviewed read-only tool choices;
- shared schema, bounds, canonicalization, platform resolution, and publisher contracts;
- private, bounded test conversations pinned to one validated draft revision;
- publish review, atomic publication, idempotency, conflict handling, and actionable errors;
- published-release inspection and explicit deprecation;
- catalog/selector support for newly created agents that have no default release;
- database, API, authorization, concurrency, frontend, accessibility, and live acceptance gates;
- operator documentation and a clean-checkout Increment 9 verification script.

Deferred:

- executable Python or other publisher-supplied code and its isolation (Increment 10);
- raw manifest, prompt-file, source-tree, archive, or dependency editing in the browser;
- creating or modifying model aliases, tool catalog entries, tool schemas, or platform policy;
- non-read-only and approval-required tools;
- collaborative simultaneous editing, comments, review assignment, or approval chains;
- automatic evaluation suites, prompt optimization, traffic splitting, or promotion workflows;
- changing an agent default, upgrading existing conversations, or migrating traffic as a
  publication side effect;
- undeprecation, deletion, replacement, or mutation of published releases and evidence;
- filesystem-import-to-draft and draft export; equivalence is proven through the shared contract,
  not by adding another transfer format.

## Fixed design decisions

1. The builder edits a typed form that maps one-to-one to the existing schema-v2 declarative
   manifest. The server, not the browser, assembles and validates the authoritative manifest.
   Unknown fields, arbitrary JSON fragments, workflow names, code, secrets, and unbounded values
   cannot enter through the draft API.
2. A mutable `agent_drafts` head is only editing convenience. Every successful save creates an
   immutable, monotonically numbered draft revision containing canonical bytes, digest, author,
   and timestamp. Validation, tests, and publication always name a revision, never "latest".
3. Draft mutation uses an explicit revision precondition. A stale update returns a stable
   `draft_revision_conflict` and does not overwrite newer work. A published draft is sealed;
   further work starts by cloning it to a new draft and choosing a new semantic version.
4. Authors may create, read, update, validate, and test only their own drafts. Publishers may
   read publish-ready drafts, publish them, and deprecate releases. `genai-admin` is not treated
   as publisher authority unless it is also mapped to the publisher role. Ordinary
   `genai-user` access grants neither authoring nor publication.
5. Use realm roles `genai-agent-author` and `genai-agent-publisher`. Route-level checks are
   performed in the API for every operation; hiding controls in the browser is not an
   authorization boundary. Existing `genai-user` remains required for ordinary portal access.
6. The UI obtains enabled model aliases and reviewed, enabled, read-only tool choices from
   bounded authoring-options endpoints. A submitted name is still resolved again by the server.
   The browser cannot submit tool IDs, schemas, provider targets, policy evidence, or permissions
   as authorities.
7. Validation has the same offline and platform stages as Increment 8 and returns the same
   versioned report shape plus revision identity. A stored report is diagnostic evidence only;
   test and publish repeat all state-dependent resolution and never treat it as authorization.
8. Draft testing is a private preview, not publication. The API creates a test session owned by
   the author and an immutable run snapshot from the named revision and its freshly resolved
   model/tools. It invokes the existing `AgentRunWorkflow`; no draft `AgentVersion`, grant,
   publication row, public conversation, or selectable catalog entry is created.
9. Test snapshots are explicitly marked `source = "draft_test"`, refer to the draft revision,
   and contain the same bounded declarative execution contract as published runs. Test tool
   authorization uses only the exact reviewed read-only tools resolved into that snapshot.
   Draft tests cannot change defaults, publish, deprecate, or access another user's conversation.
10. Test sessions are single-user, single-revision conversations with the normal turn limits,
    cancellation, event streaming, model gateway, tool gateway, redaction, and audit behavior.
    A newer save never changes an existing test session; the UI clearly labels the revision and
    digest under test.
11. Portal publication constructs a `Candidate` from the selected canonical revision and calls
    the same publisher boundary used by the CLI. The boundary accepts explicit provenance and
    actor context; adapters do not duplicate resolution, persistence, idempotency, or conflict
    rules.
12. Publication revalidates the revision inside the transaction. It writes provenance `portal`,
    `draft_id`, draft revision, publisher ID, canonical digest, bounded validation report, exact
    model/tool resolutions, and timestamp. It never records bearer tokens, prompt copies,
    browser state, credentials, or unbounded error payloads in audit fields. The API requires at
    least one successful test turn for that exact revision and digest; UI state alone never
    satisfies this gate.
13. Filesystem and portal candidates with identical manifest semantics produce identical
    canonical bytes and digest. Existing global digest uniqueness means the first published
    release owns that identity; an equivalent second attempt returns an idempotent result only
    for the same `(agent_id, version, digest)` and otherwise returns the existing stable conflict.
14. Existing stable agent metadata is not mutated by publishing another version. A candidate for
    an existing slug must match its stable name and description exactly. Changing display
    metadata is deferred to a separate audited operation; the builder explains mismatches before
    publication.
15. Publication never sets `agents.default_version_id`. Catalog discovery must therefore expose
    every agent having at least one nondeprecated published release, including a newly created
    agent whose default is null. Conversation creation continues to require one explicit
    published version ID when no default exists.
16. Deprecation is the only mutable published lifecycle transition in scope:
    `published -> deprecated`. It is an audited, idempotent operation. Deprecated releases are
    excluded from new selection and new conversation creation, but remain readable to owners of
    existing conversations and executable by already accepted snapshots.
17. Deprecating the current default is rejected until an already supported explicit default
    management operation selects another published release; adding that operation is not part of
    this increment. Deprecation never silently chooses a replacement or rewrites a conversation.
18. Drafts, revisions, validations, test sessions, and publication attempts are bounded and
    retained for audit in Increment 9. No cleanup job or destructive rollback is introduced.
19. API errors use stable codes and field paths. Internal exceptions, SQL details, absolute
    paths, catalog configuration, provider responses, and credentials are not returned to the
    browser.
20. Database migrations are additive. Runtime execution continues to depend only on immutable
    snapshots and artifacts, not on draft availability or the portal builder deployment.

## Draft and revision contract

The builder exposes these schema-v2 fields:

- agent slug, semantic version, display name, and description;
- bounded system instructions;
- one enabled model alias;
- zero or more enabled reviewed read-only tools by stable name;
- the existing execution limits, including iterations, calls per step, argument/result bytes,
  and output tokens.

Server responses include a draft ID, revision number, state, digest, ownership metadata,
validation summary, test summary, and timestamps. They never echo resolved provider credentials
or hidden platform configuration.

Use an additive `agent_draft_revisions` record, conceptually:

```text
id, draft_id, revision, manifest, canonical_content, digest,
author_id, created_at
```

Enforce unique `(draft_id, revision)`, canonical size bounds, digest/content agreement, and
update/delete rejection. The draft head records the current revision and lifecycle state:
`editing`, `validated`, `publish_ready`, or `published`. State is a workflow aid, not proof that
platform dependencies are still valid.

Saving accepts structured fields and `expected_revision`. The API validates syntax, identity,
runtime support, semantics, and bounds before inserting the next revision. Invalid edits return
field errors without creating a revision. Validation inserts or replaces no manifest data; it
records a bounded report keyed by revision and marks the head validated only if that revision is
still current.

The version belongs to the revision identity. Authors cannot publish placeholder versions or
ask the server to auto-increment them. A collision with a published release is visible during
validation and is checked again transactionally during publication.

## Shared publication boundary

Refine the Increment 8 publisher into adapter-neutral inputs without changing CLI behavior:

```python
@dataclass(frozen=True)
class Candidate:
    manifest: dict[str, object]
    artifact: bytes
    digest: str
    source: CandidateSource

@dataclass(frozen=True)
class PublicationContext:
    provenance: Literal["filesystem", "portal"]
    actor_id: UUID | None
    draft_id: UUID | None
    draft_revision: int | None

async def validate_candidate(session, candidate, *, platform: bool) -> ValidationReport: ...
async def publish_candidate(session, candidate, context) -> PublishResult: ...
```

Add one pure `candidate_from_manifest` constructor that uses the same schema validation and
`canonical_manifest` implementation as filesystem loading. `candidate_from_directory` remains a
strict filesystem adapter and delegates after its path/file checks. The web route constructs no
artifacts and performs no direct publication writes.

Within one transaction, portal publication must:

1. lock the named draft and revision and verify the current revision precondition;
2. verify author/publisher access, a successful test for the exact revision/digest, and that the
   draft is not already sealed inconsistently;
3. repeat candidate validation and exact model/tool resolution;
4. apply the existing advisory lock, idempotency, version-conflict, and digest-conflict rules;
5. create or verify stable agent metadata, artifact, draft-status version, exact grants, portal
   publication audit, and publication-attempt audit;
6. change the release to published only after every write succeeds;
7. seal the draft at the published revision and commit;
8. return the existing release/publication identities after commit.

Failure leaves the draft editable or publish-ready as appropriate and records a bounded failed
attempt outside the publication transaction only when that can be done without masking the
original error. It must never leave a partial artifact, release, grant set, published state, or
sealed draft.

## Private draft test contract

Add bounded `agent_draft_test_sessions` and `agent_draft_test_turns` (or equivalently separated
preview records) rather than overloading public `conversations`. Each session records owner,
draft revision, validation digest, run snapshot, status, and timestamps. Authorization queries
always include the owner ID.

Extend the immutable run-snapshot source contract so exactly one source is present:

```text
published run: agent_version_id set, draft_revision_id null
draft test:    agent_version_id null, draft_revision_id set
```

The snapshot itself remains the sole runtime behavioral authority. Loading and tool
authorization accept draft-test snapshots only when the test marker, owner-scoped test turn,
revision digest, declarative runtime contract, and exact resolved tool records agree. Production
conversation acceptance continues to require a published, nondeprecated version and can never
submit a draft snapshot.

No new Temporal workflow type or task queue is introduced. Draft tests use
`AgentRunWorkflow` on `porfirium-agent-runtime-v1` with distinct workflow IDs and observations.
Tests prove workflow replay and worker restart behavior for both snapshot source variants.

## API contract

Add versioned endpoints with bounded request/response models:

```text
GET    /api/v1/agent-authoring/options
GET    /api/v1/agent-drafts
POST   /api/v1/agent-drafts
GET    /api/v1/agent-drafts/{draft_id}
PATCH  /api/v1/agent-drafts/{draft_id}
POST   /api/v1/agent-drafts/{draft_id}/clone
POST   /api/v1/agent-drafts/{draft_id}/revisions/{revision}/validate
POST   /api/v1/agent-drafts/{draft_id}/revisions/{revision}/tests
GET    /api/v1/agent-draft-tests/{test_id}
POST   /api/v1/agent-draft-tests/{test_id}/turns
POST   /api/v1/agent-draft-tests/{test_id}/cancel
POST   /api/v1/agent-drafts/{draft_id}/revisions/{revision}/publish
GET    /api/v1/agent-publications/{publication_id}
POST   /api/v1/agents/{agent_slug}/versions/{version}/deprecate
```

Mutation requests require an idempotency key where retry could duplicate durable work. Draft
updates additionally require `expected_revision`; publish requires the exact draft revision and
digest shown in review. Test-turn submission uses the existing single-in-flight and bounded
idempotency semantics.

Use stable HTTP behavior:

- `401` for missing/invalid authentication;
- `403` for a missing role or inaccessible resource without disclosing another author's draft;
- `404` for absent owner-scoped resources;
- `409` for stale revision, active test turn, lifecycle, version, or digest conflicts;
- `422` for structured field/schema validation;
- `503` for platform dependency resolution or test-runtime unavailability where retry is safe.

Error bodies include `code`, concise `message`, optional bounded `field_errors`, and correlation
ID. Publication resolution failures preserve the Increment 8 stable error codes.

## Portal experience

Add an Authoring workspace only for authors and publishers:

- draft list showing owner-visible state, target identity/version, revision, validation, test,
  and last-updated time;
- create/clone form with sections for identity, instructions, model, tools, and limits;
- inline client hints backed by authoritative server errors;
- validation summary showing canonical digest and exact resolved model/tool schema versions;
- test panel clearly marked non-production, pinned to revision/digest, with normal streaming,
  tool-call status, cancellation, and a reset that creates a new private session;
- publish review showing all contract fields and warning that a published version is immutable;
- publisher-only publish action and lifecycle view;
- release detail showing provenance, author, publisher, digest, validation, and timestamps;
- publisher-only deprecate confirmation explaining impact on selection and existing runs.

Dirty edits invalidate the visible validation/test readiness until saved as a new revision. The
UI never implies that an earlier revision's successful validation or test applies to the current
head. Publish controls remain disabled unless the viewed revision is current, platform-valid,
successfully tested, and the caller is a publisher; the API independently enforces all rules.

The ordinary Agent selector lists every selectable published version, groups versions by agent,
marks the configured default without requiring one, and excludes deprecated versions for new
conversations. Existing conversations pinned to a deprecated version remain labeled and
readable; they are not silently upgraded.

Keyboard navigation, labels, focus movement after errors, non-color status cues, and reduced
motion behavior are part of acceptance. Responsive behavior must preserve the existing chat
workflow rather than turning the builder into the default landing view.

## Implementation sequence

### Increment 9.1 — Shared contracts, roles, and immutable revisions

- extract adapter-neutral candidate creation and explicit publication context from the current
  filesystem publisher while preserving all CLI output and behavior;
- add author/publisher role dependencies and Keycloak realm/bootstrap configuration;
- add immutable draft revisions, optimistic concurrency, lifecycle constraints, and audit events;
- expose bounded authoring options from enabled model and reviewed read-only tool catalogs;
- add owner-scoped draft CRUD and clone APIs with stable errors;
- prove canonical equality between form-built and filesystem-loaded candidates.

Checkpoint: two semantically identical form/filesystem manifests produce byte-identical
artifacts and digest; stale saves cannot overwrite work; user, author, publisher, and combined
role matrices fail closed at the API and database ownership boundaries.

### Increment 9.2 — Validation and private draft testing

- persist revision-keyed bounded validation evidence using shared offline/platform validation;
- add private test session/turn records and the exactly-one-source snapshot constraint;
- route draft tests through the existing generic workflow and task queue;
- adapt plan loading and tool authorization to exact draft-test snapshot evidence without
  weakening published-run checks;
- add owner isolation, idempotency, cancellation, restart, replay, and observability tests;
- expose test event polling/streaming using the existing bounded conversation patterns.

Checkpoint: an author can test one exact revision with no-tool and reviewed-tool turns, observe
its digest, save a newer revision without changing the active test, and resume the original test
after a worker restart; no draft appears in the public catalog or ordinary conversation API.

### Increment 9.3 — Portal publication and lifecycle

- add publish review and publisher-only publication APIs through the shared boundary;
- persist portal actor, draft/revision provenance, attempts, and successful publication evidence;
- seal successful drafts and implement retry/concurrency/conflict behavior;
- add audited, idempotent published-to-deprecated transition and admission filtering;
- update catalog discovery for published agents without defaults and preserve selection pinning;
- add publication/release detail APIs with role-appropriate redaction.

Checkpoint: publication failure leaves no selectable or partial release; an identical retry
returns the original identities; a newly created agent with no default is explicitly selectable;
deprecation blocks new selection without changing existing conversations or accepted runs.

### Increment 9.4 — Builder UI and M4 equivalence gate

- implement draft list, structured editor, validation, test, review, publish, release detail, and
  deprecation views;
- condition navigation and actions on roles while retaining server-side enforcement;
- add accessible status/error handling, stale-revision recovery, responsive layout, and tests;
- add `docs/architecture/INCREMENT9_RUNBOOK.md` and `scripts/increment9/verify.sh`;
- execute portal/filesystem equivalence, unchanged-runtime, deprecation, and rollback live gates.

Checkpoint: an authorized user can complete the documented workflow from an empty draft to a
selected live release, while an equivalent filesystem candidate yields the same release
contract and execution behavior. M4 is ready for user acceptance.

## Test and acceptance matrix

### Automated tests

- structured form fields round-trip to the schema-v2 manifest with canonical digest stability;
- unknown fields, invalid semantic versions, unsupported runtime values, oversized strings,
  invalid limits, duplicate tools, secrets-like prohibited fields, and disabled catalog choices
  fail closed;
- enabled model/tool options are bounded and contain no provider credentials or hidden policy;
- every draft query and mutation is owner-scoped; cross-user IDs do not disclose content;
- ordinary user, author, publisher, administrator-only, and combined-role behavior matches the
  fixed role matrix;
- saves create immutable sequential revisions; stale and concurrent saves converge to one winner;
- validation is revision-specific and repeats current model/tool resolution;
- draft tests create no agent version, grant, publication, public conversation, or catalog row;
- draft-test snapshots have exactly one source, are immutable, and reject forged owner, revision,
  digest, model, tool, schema, and runtime data;
- test turns retain normal idempotency, single-flight, cancellation, bounds, restart, replay,
  event ordering, and safe error behavior;
- save or validation during a test cannot alter its snapshot or outcome;
- portal and filesystem adapters produce identical canonical bytes, digest, platform resolution,
  grants, and runtime snapshot for the same manifest;
- portal publication creates artifact, release, grants, publication, draft seal, and audits
  atomically; injected failures roll back all selectable state;
- same release/digest retry is idempotent; changed digest/version and concurrent portal/CLI
  publication return deterministic conflicts without partial data;
- publishing an existing slug with changed stable metadata fails without mutating the agent;
- publication never changes a default, conversation selection, accepted snapshot, or history;
- catalog discovery includes published agents with no default and excludes deprecated releases
  from new selection;
- deprecation is authorized, audited, idempotent, rejects current defaults, and does not block
  already accepted snapshots;
- frontend covers roles, field errors, stale revision, validation invalidation, test pinning,
  publish confirmation, conflict recovery, deprecation messaging, and keyboard interaction;
- existing CLI, catalog, generic runtime, API, frontend, migration, and Increment 8 regression
  suites remain green.

### Live acceptance

1. Start from the accepted Increment 8 stack and record image IDs, migration revision, roles,
   catalog/defaults, and generic worker poller.
2. Verify an ordinary user cannot discover or call authoring/publishing endpoints; verify an
   author can manage only their own drafts and cannot publish or deprecate.
3. Create a new declarative agent draft in the portal using one model alias and the two
   unambiguous time tools; save revisions and prove stale-update protection.
4. Validate the current revision and record its digest and exact model/tool resolutions. Disable
   or make a dependency ambiguous in an isolated fixture and prove revalidation fails safely.
5. Run a no-tool and a time-tool test turn. Save a newer revision during an active test, restart
   the worker, and prove the turn completes from the original test snapshot and digest.
6. Confirm the draft and its tests are absent from public agent and conversation catalogs and are
   inaccessible to another author.
7. As a publisher, review and publish the tested revision. Repeat the identical request and
   require the same release/publication identities and exactly one immutable release.
8. Without rebuilding Portal API or worker, select the new version in an ordinary new
   conversation and complete no-tool and reviewed-tool turns through `AgentRunWorkflow`.
9. Build the same manifest as a filesystem candidate. Require the same canonical digest and
   resolution report; demonstrate the documented idempotent or digest-conflict outcome dictated
   by the already-published identity, with no second artifact or divergent grants.
10. Attempt an unauthorized publish, changed-content same-version publish, stale-revision
    publish, metadata mismatch, and injected transaction failure; require stable errors and no
    partial/selectable state.
11. Deprecate a non-default release while one accepted run is active. Require it to disappear
    from new selection, reject new conversations, and allow the accepted run and existing
    conversation history to remain pinned and complete.
12. Attempt to deprecate the current default and require a safe conflict without choosing a
    replacement. Roll back operationally by selecting a prior published version in a new
    conversation.
13. Run backend lint/tests, frontend lint/tests/typecheck/build, Compose validation, secret scan,
    Increment 8 regressions, and the Increment 9 verification script from a clean checkout.

Use the minimum paid Yandex calls needed to prove one draft test and one published execution.
Reuse recorded successful evidence for no-tool or duplicate paths where deterministic fixtures
cover the contract.

## Operational rollout

1. Add the author and publisher realm roles without assigning them broadly; grant a dedicated
   acceptance author and publisher explicitly.
2. Apply additive draft-revision, test, publication-attempt, audit, and snapshot-source
   migrations before deploying the API and worker that understand them.
3. Deploy backend compatibility first, run Increment 8 regressions, then deploy the builder UI.
4. Keep authoring navigation feature-disabled until role mapping, owner isolation, and API gates
   pass in the live environment.
5. Enable authoring for the acceptance author, validate/test a canary, then enable publication
   for the acceptance publisher.
6. Publish without changing defaults, explicitly select the canary, execute the live gate, and
   record draft/revision/test/snapshot/release/publication/digest/workflow identifiers.
7. Enable the feature for intended roles only after acceptance. Record M4 complete separately;
   Increment 10 remains required before any executable package support.

## Rollback

Builder rollback is control-plane isolation:

1. disable authoring UI navigation and reject new draft/test/publication mutations with a
   documented feature switch;
2. allow accepted draft-test and published runs to finish from their immutable snapshots;
3. stop selecting a faulty release, or deprecate it if it is not the current default;
4. select a previously accepted published release for new conversations;
5. roll back the UI/API deployment only to a version that tolerates the additive rows and
   snapshot source contract;
6. retain all drafts, revisions, tests, artifacts, releases, grants, audits, snapshots,
   conversations, and Temporal histories.

Do not delete portal-created releases, edit manifests or grants, rewrite draft test evidence,
change defaults implicitly, downgrade past migrations used by retained rows, or restore service
with ad hoc SQL.

## Exit gate

Increment 9 is accepted only when separately authorized authors and publishers can create,
revise, validate, privately test, publish, inspect, select, execute, and safely deprecate a
declarative portal-created agent; the same manifest through the portal and filesystem adapters
produces identical canonical artifact and release behavior; invalid or stale drafts never become
selectable; test and production runs remain pinned across edits, publication, deprecation, and
worker restart; and all Increment 8 CLI/runtime behavior remains intact.
