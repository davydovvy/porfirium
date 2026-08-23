# Increment 8 — Filesystem and CLI publication plan

Status: Implemented on 2026-08-23; awaiting user acceptance
Target milestone: M4 — Independent publication (filesystem half)
Prerequisite: Increment 7 generic runtime accepted

## Outcome

Increment 8 lets an operator develop a declarative agent release in a versioned source
directory, validate it with a repository CLI, publish it through the same platform application
service that Increment 9 will reuse, inspect the resulting immutable release, and select it for
an Agent conversation without rebuilding the Portal API or agent worker.

This increment deliberately supports only the schema-v2 declarative contract already executed
by `AgentRunWorkflow`. A published artifact is the bounded canonical manifest stored by the
platform, not a live directory or bind mount. Python entrypoints, dependency builds, archive
uploads, arbitrary package files, and execution of publisher-supplied code remain deferred to
Increment 10.

The increment is complete when a new `tool-assistant` version, created outside the application
source, passes offline and platform validation, is published atomically, appears through the
existing catalog API, executes through the unchanged generic worker, and can be rolled back by
selecting the prior published version. Existing conversations and accepted runs remain pinned.

## Scope

Included:

- a repository-owned `porfirium agents` CLI with `validate`, `publish`, and `status` commands;
- strict filesystem candidate discovery rooted at one explicit `<agent-id>/<version>` directory;
- schema-v2 declarative manifests represented as canonical JSON artifacts;
- one reusable publication application service, independent of CLI and future HTTP adapters;
- model-alias and exact tool-catalog resolution against current platform state;
- atomic creation of agent identity, immutable version, grants, artifact, and publication audit;
- safe idempotency for retrying the same identity and digest;
- human-readable output plus stable JSON output and exit codes for automation;
- unit, database integration, concurrency, clean-checkout, and live execution gates;
- operator documentation for publish, diagnose, select, and selection rollback.

Deferred:

- portal drafts, authoring, test conversations, publication, and deprecation UI (Increment 9);
- executable source, Python entrypoints, dependency locks, build jobs, and sandboxing
  (Increment 10);
- automatic directory watching or background scanning;
- remote registries, signing, attestations, promotion between environments, and artifact
  garbage collection;
- publication of new model aliases, tools, schemas, or permissions from a package;
- changing an agent's default release as an implicit effect of publication;
- mutating, replacing, or deleting a published release, artifact, grant, snapshot, or history.

## Fixed design decisions

1. The accepted package layout is exactly `agents/<agent-id>/<semver>/manifest.json` for this
   increment. The command receives the version directory, not the repository root. Symlinks,
   special files, nested manifests, and files other than `manifest.json` are rejected. This is
   a complete declarative package, not an extensible source archive.
2. Only manifest schema version 2 with `runtime.kind = "declarative"` and
   `runtime.contract_version = 1` is publishable. Schema-v1 manifests remain readable for
   historical digest validation but cannot be newly published or executed.
3. Canonical UTF-8 JSON from the already-defined `canonical_manifest` function is the complete
   artifact. Its SHA-256 digest is both artifact identity and release digest. Formatting and
   object-key order do not affect it; any semantic manifest change does.
4. Validation has two explicit levels. Offline validation checks package safety, JSON/schema,
   identity/path agreement, bounds, runtime support, and digest. Platform validation additionally
   resolves the enabled model alias and every declared tool to one unambiguous, enabled,
   read-only catalog entry.
5. A bare stable tool name is publishable only when it resolves to exactly one enabled catalog
   schema. Ambiguity fails closed and tells the author to wait for a future manifest contract
   that can pin a schema version. Increment 8 does not guess newest or latest. The filesystem
   `tool-assistant:1.3.0` canary therefore grants only the two unambiguous time tools; bundled
   historical releases retain their already-resolved exact grants.
6. The publication transaction creates or verifies the stable `agents` identity, inserts the
   immutable artifact and `agent_versions` row in draft state, inserts grants, records one
   `agent_publications` audit, and changes the version to published only after all validation
   succeeds. No partially selectable release may be committed.
7. Retrying `(agent_id, version, digest)` is a successful no-op that returns the existing release
   and original publication identity. Reusing `(agent_id, version)` with another digest, or one
   digest under another release identity, fails with a stable conflict. Concurrent publishers
   have the same outcomes through database constraints and transaction handling.
8. Publication never changes `agents.default_version_id`, upgrades a conversation, or starts a
   run. Selection remains an explicit existing API operation. Rollback means selecting a prior
   published version for a new conversation; it never rewrites an existing conversation or run.
9. The CLI is an operator control-plane client packaged from the Portal API Python project. It
   calls the application service directly with configured database access; it does not call
   private ORM helpers, modify SQL ad hoc, require the Portal API process to be running, or
   require provider credentials for offline validation.
10. Publication provenance is `filesystem`. The audit contains bounded validation facts,
    package-relative source identity, digest, resolved model/tool identifiers and schema
    versions, CLI version, timestamp, and an optional authenticated operator identity. It never
    stores absolute host paths, environment values, credentials, or manifest instructions as
    duplicated audit text.
11. The generic runtime continues to execute the immutable acceptance snapshot made from the
    published database release. Neither Portal API nor worker reads the source directory or
    artifact filesystem after publication.
12. Database migrations and publication are additive. Rollback never deletes published data.

## Candidate and artifact contract

The focused package is:

```text
agents/
  tool-assistant/
    1.3.0/
      manifest.json
```

`manifest.json` uses the existing schema-v2 shape. No new authoring syntax is introduced in
Increment 8. Authors copy a prior declarative version, change `agent.version` and intended
behavior, then validate the new directory.

The validator applies these stages in order:

1. resolve the supplied path without following a candidate-controlled symlink;
2. require the exact two-segment identity suffix and one regular `manifest.json` file;
3. bound file size before reading, decode strict UTF-8, reject duplicate JSON keys, and require
   one JSON object;
4. validate schema, runtime contract, all existing field bounds, and path/manifest identity;
5. canonicalize once and compute `sha256:<hex>`;
6. when platform validation is requested, resolve model and tools and produce a normalized
   validation report.

Add a small immutable-artifact record (or equivalently constrained artifact columns if the
implementation proves simpler) containing at least content digest, media type, canonical bytes,
size, and creation time. The database must reject artifact update/delete and require the
published `agent_versions.digest` to equal its artifact digest. The artifact size is bounded by
the manifest limit; arbitrary auxiliary files are not stored.

The validation report is versioned and bounded. It records facts needed to explain publication,
not a second behavioral authority. Runtime snapshots continue to derive behavior from the
immutable release manifest and exact resolved grants.

## Publication application service

Introduce one application-facing boundary with typed inputs and results, conceptually:

```python
class AgentPublisher:
    async def validate(self, candidate: AgentCandidate, *, platform: bool) -> ValidationReport: ...
    async def publish(self, candidate: AgentCandidate, actor: PublicationActor) -> PublishResult: ...
    async def status(self, agent_id: str, version: str) -> ReleaseStatus: ...
```

Filesystem reading and persistence are adapters around this service. The core service owns
manifest validation, resolution, conflict rules, transaction boundaries, and safe result/error
contracts. Increment 9 must be able to supply canonical draft content to the same service
without pretending that a portal draft is a filesystem directory.

Publication performs all state-dependent checks again inside the transaction; a prior
`validate` command is useful feedback, not an authorization token. It must:

- resolve exactly one enabled model alias and retain its immutable database identifier;
- resolve every stable tool name to one enabled, read-only catalog entry and retain its exact
  identifier/schema;
- reject duplicate, missing, disabled, non-read-only, or ambiguous entries;
- verify an existing agent identity has metadata consistent with the candidate, or define a
  narrowly tested rule that release metadata does not mutate stable agent metadata;
- persist grants using resolved tool IDs and a publication-specific policy evidence value;
- insert the artifact, release, grants, and audit before making the release published;
- translate expected uniqueness races to stable idempotent success or conflict;
- return only after the transaction commits.

No network discovery is performed during publication. Tools and model aliases must already have
been reviewed into the platform catalog. Provider or MCP availability affects later canary
execution, not whether a declarative contract is internally valid.

## CLI contract

Expose a console entry point named `porfirium` from the existing Python package:

```text
porfirium agents validate <version-directory> [--platform] [--json]
porfirium agents publish <version-directory> [--json]
porfirium agents status <agent-id>:<version> [--json]
```

Behavior:

- `validate` is offline by default and needs neither database nor running services;
- `validate --platform`, `publish`, and `status` use the same database configuration and fail
  clearly when it is absent or unreachable;
- `publish` always repeats offline and platform validation;
- `status` shows identity, lifecycle status, digest, artifact size, provenance, publication time,
  resolved model alias/target, and granted stable tool/schema pairs;
- normal output is concise and redacts connection data; `--json` has a versioned schema,
  deterministic key ordering, and no ANSI formatting;
- success exits `0`; validation failure, conflict, missing release, configuration/dependency
  failure, and internal failure use documented distinct nonzero codes;
- errors have stable machine codes such as `candidate_invalid`, `platform_resolution_failed`,
  `release_version_conflict`, and `release_not_found`, without tracebacks unless an explicit
  debug option is selected.

Commands do not expose an option to overwrite, delete, force-publish, set a default, edit grants,
or bypass validation.

## Implementation sequence

### Increment 8.1 — Extract publisher contracts and harden candidates

- separate pure canonicalization/schema logic from filesystem candidate loading;
- add strict JSON decoding, size limits, regular-file/symlink checks, and exact package shape;
- define typed candidate, artifact, validation report, actor, result, status, and stable-error
  contracts;
- keep historical schema-v1 loading tests while rejecting schema v1 as a new candidate;
- add an example independently developed `tool-assistant:1.3.0` candidate only when the
  implementation increment begins, not as a migration seed.

Checkpoint: offline validation produces the same digest for semantically identical JSON and
rejects unsafe paths, malformed content, unsupported runtime, identity mismatch, duplicate
keys, oversize content, and extra files without touching the database.

### Increment 8.2 — Artifact persistence and atomic publisher

- add the immutable bounded artifact persistence contract and database enforcement;
- implement platform model/tool resolution with ambiguity and enabled/read-only checks;
- implement the single publication transaction and filesystem provenance audit;
- preserve published version, grant, and snapshot immutability triggers;
- implement exact retry idempotency and deterministic conflict handling, including concurrency;
- expose read-only status through the same publisher boundary.

Checkpoint: injected failure at every transaction stage leaves no artifact-only, draft,
grant-only, audit-only, or published partial state; concurrent identical publication converges
on one release and conflicting publication preserves the first release unchanged.

### Increment 8.3 — CLI and operator workflow

- add the `porfirium` console entry point and three commands;
- provide stable text/JSON output, error codes, database lifecycle, and redaction;
- make the CLI runnable from the documented host `uv` workflow and an existing application
  container without rebuilding after each candidate change;
- document candidate copy/edit/validate/publish/status and catalog selection;
- add `scripts/increment8/verify.sh` using isolated test fixtures and the existing stack.

Checkpoint: an operator can publish a newly copied version from a staging directory and inspect
the exact catalog/artifact/grants using only documented commands.

### Increment 8.4 — Live independence and rollback gate

- publish a distinct declarative canary version without rebuilding Portal API or worker images;
- prove it appears in existing catalog endpoints and can be selected for a new conversation;
- execute no-tool and reviewed-tool turns through the unchanged `AgentRunWorkflow`;
- publish or edit another candidate while a run is active and prove the run's snapshot/digest
  does not drift;
- select the prior published version in a new conversation and execute it successfully;
- restart Portal API and worker after removing the candidate source directory and prove both
  published versions remain selectable and executable.

Checkpoint: the transition-plan Increment 8 exit gate passes with database and Temporal evidence,
and no runtime process has a candidate-directory mount or source-path dependency.

## Test and acceptance matrix

### Automated tests

- valid schema-v2 candidate, canonical digest stability, path identity, and bounded output;
- missing/extra/symlink/special files, traversal-like inputs, invalid UTF-8, duplicate JSON keys,
  malformed JSON, oversize input, schema-v1 publication, unknown fields/runtime, and invalid
  semantic version all fail closed;
- offline validation performs no database or network access;
- missing, disabled, non-read-only, duplicated, and ambiguous tools fail platform validation;
- missing or disabled model alias fails platform validation;
- publication creates one artifact, version, complete grant set, and audit atomically;
- failure injection at each write rolls back the complete transaction;
- same identity/digest retry is idempotent; same identity/different digest and digest reuse under
  another identity are conflicts; concurrent cases converge deterministically;
- published artifacts, versions, and grants reject update/delete, while deprecation-compatible
  lifecycle behavior remains possible for Increment 9;
- publication does not change a default version, existing conversation selection, accepted run
  snapshot, or completed history;
- status is read-only, accurately reports resolved identities, and redacts configuration;
- CLI text/JSON schemas and exit codes are stable and tested through subprocess invocation;
- existing catalog, generic runtime, manifest-v1 compatibility, API, and frontend tests remain
  green.

### Live acceptance

1. Start from the accepted Increment 7 stack and record image IDs, default release, catalog, and
   database migration revision.
2. Copy a declarative release to a new semver directory and make a harmless, visible instruction
   or bounded-limit change.
3. Run offline validation with the database stopped or inaccessible; verify identity and digest.
4. Run platform validation, publish, repeat the identical publish, and inspect status; require one
   immutable release/publication and a stable idempotent result.
5. Attempt the same version with changed content and candidates with an unknown model/tool;
   require conflicts/failures and no partial rows.
6. Without rebuilding Portal API or worker, confirm the release through the API, select it in a
   new conversation, and complete both no-tool and tool-using Agent turns.
7. Start a turn on the new version, change a newer candidate or catalog default while it is
   active, restart the worker, and prove completion uses the original snapshot and digest.
8. Select the prior published version in another new conversation and execute it successfully;
   verify the first conversation and all completed snapshots remain unchanged.
9. Remove or move the candidate source directory, restart application services, and repeat a run
   from the published release to prove source independence.
10. Run backend lint/tests, frontend lint/tests/build, Compose validation, Increment 7 regression,
    and the new Increment 8 verification script from a clean checkout.

No additional paid model canary is required if the live acceptance turns already exercise the
configured Yandex route once each for the new and prior releases. Record and reuse that evidence
rather than duplicating paid calls.

## Operational rollout

1. Apply the additive artifact/publication migration and deploy the CLI-bearing Portal API image.
2. Run the complete pre-publication regression gate; no Agent maintenance window is required.
3. Validate and publish the canary. Publication does not alter the default or existing traffic.
4. Select the canary only in a new controlled conversation and complete the live gates.
5. Leave both prior and canary releases published and record their digests, publication IDs,
   artifact sizes, grants, conversation IDs, run snapshot IDs, and workflow IDs.
6. Update results/status documentation only after user acceptance.

## Rollback

Runtime rollback is selection-only:

1. stop selecting the new version for new conversations;
2. select the previously accepted published version in a new conversation;
3. allow accepted runs on either version to finish on their pinned snapshots;
4. if future lifecycle support is available, deprecate the faulty version only to prevent new
   selection—do not mutate or delete it;
5. diagnose publisher/CLI deployment independently; the generic runtime requires no rollback.

If the database or CLI deployment must be rolled back, first stop filesystem publication and
keep all already published releases, artifacts, grants, audits, conversations, snapshots, and
Temporal histories. Do not downgrade past an additive migration while retained rows depend on
it, and never restore service by editing catalog rows manually.

## Exit gate

Increment 8 is accepted only when a new independently developed declarative version can be
copied, validated, atomically published, inspected, selected, executed, and selection-rolled
back without rebuilding the Portal API or agent worker; publication retry and conflict behavior
is proven; active runs remain pinned across worker restart and later publication; and removing
the source directory does not affect the immutable published release.
