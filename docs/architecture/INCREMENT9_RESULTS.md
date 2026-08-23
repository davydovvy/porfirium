# Increment 9 — Portal declarative agent builder results

Status: Implemented candidate; live role and user acceptance pending
Date: 2026-08-23

## Delivered

- separate `genai-agent-author` and `genai-agent-publisher` authorization gates;
- owner-scoped structured draft creation and editing with immutable canonical revisions and
  optimistic concurrency;
- platform validation using the same schema, canonicalization, model resolution, and exact
  reviewed read-only tool resolution as filesystem publication;
- private draft-test conversations pinned to an immutable revision and executed by the existing
  `AgentRunWorkflow` on `porfirium-agent-runtime-v1`;
- an exact-revision successful-test gate before publication;
- portal publication through the shared publisher with actor, draft, revision, validation,
  digest, and `portal` provenance evidence;
- audited `published -> deprecated` lifecycle handling that preserves existing conversations,
  snapshots, artifacts, grants, and histories;
- catalog discovery for published agents without an implicitly assigned default;
- a role-gated structured Agent Builder UI and Increment 9 operator runbook;
- additive migration `0010_portal_builder` and an automated Increment 9 verification gate.

## Verification evidence

The following passed on 2026-08-23:

- backend Ruff and 43 Pytest tests;
- frontend ESLint, 4 Vitest tests, TypeScript, and production Vite build;
- Increment 7 generic-runtime static regression;
- Increment 8 filesystem publication and CLI regression;
- Increment 9 static and unit verification;
- live additive migration from `0009_filesystem_publication` to `0010_portal_builder`;
- live Portal API and portal health checks;
- live generic worker startup on the unchanged `porfirium-agent-runtime-v1` queue.

The first live migration attempt exposed that asyncpg does not accept multiple SQL commands in
one prepared statement. PostgreSQL rolled the migration back transactionally. The migration was
corrected to create the immutability function and trigger in separate statements, then applied
successfully at revision `0010_portal_builder`.

## Acceptance remaining

Increment 9 and Milestone M4 are not yet accepted. The remaining gate is operational:

1. assign `genai-agent-author` and `genai-agent-publisher` independently in Keycloak;
2. refresh the acceptance users' sessions and verify the user/author/publisher role matrix;
3. create, revise, validate, and privately test a declarative draft through the portal;
4. publish it as an authorized publisher and execute the selected release;
5. prove filesystem/portal canonical equivalence and safe deprecation behavior;
6. obtain user acceptance and record the live identifiers and results.

Use the [Increment 9 runbook](INCREMENT9_RUNBOOK.md) for this workflow. Do not mark Increment 9 or
M4 accepted until these live steps and user confirmation are complete.

## Rollback

Remove the author/publisher role assignments or disable access to the builder to stop new
control-plane mutations. Allow accepted test and production runs to finish from their immutable
snapshots. Stop selecting or deprecate a faulty non-default release, then explicitly select a
prior accepted version. Retain all drafts, revisions, artifacts, releases, grants, audits,
snapshots, conversations, and Temporal histories.
