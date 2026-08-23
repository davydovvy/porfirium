# Increment 9 — Portal declarative agent builder results

Status: Completed and accepted
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

- backend Ruff and 44 Pytest tests;
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

During live private testing, the first **Run test** request exposed an unordered ORM flush:
SQLAlchemy attempted to insert the user message before its referenced turn, and PostgreSQL
correctly rejected the write. The endpoint now flushes the turn before adding its first message,
with a regression test that enforces that ordering. The rebuilt Portal API completed the same
private test successfully.

Live portal evidence:

```text
draft: 2bb51c16-63ec-4a46-95e3-e542d802c560
revision: 2 (ef0fbc24-def1-41d7-b193-f0181c4b2724)
digest: sha256:435de652a303f4db0ce60d30e376a924c0d7a1cef3c28ce195d60e1fb415f859
private test: 769a0a69-7aa6-42f6-b7b7-b3f62ce70b4b
test conversation: 30d75202-9380-4389-b476-5b25e7179233
test turn: eded748d-d7a7-4601-897d-4eb97e453c04
test snapshot: 371276ac-6f88-413a-9e06-62abad2ab71f
test workflow: porfirium-agent-eded748d-d7a7-4601-897d-4eb97e453c04
release: 502aa1d5-9e09-4e89-a959-1fc64988b04c
publication: ab6406ac-4fdf-4aad-8479-97cc92484f05
production turn: 76e65585-d116-41ca-82f4-09981f4d79b4
production snapshot: 20cd2c55-1e1b-4ffc-8bde-c840c40c8ec6
production workflow: porfirium-agent-76e65585-d116-41ca-82f4-09981f4d79b4
```

The published `portal-assistant:1.0.0` release retained the revision's canonical digest and
`portal` provenance, and both its private test and selected production run completed through the
unchanged generic workflow.

## User acceptance

After the private-test ordering defect was corrected and the exact Increment 9 verification gate
passed, the user confirmed on 2026-08-23 that everything worked as expected. Increment 9 and
Milestone M4 are accepted.

The final acceptance regression run executed `scripts/increment9/verify.sh` followed by
`scripts/increment8/verify.sh`. Increment 9 passed Ruff, 44 backend tests, frontend ESLint, 4
frontend tests, TypeScript, and the production build. Increment 8 then passed canonical
filesystem validation, Ruff, and the same 44-test backend suite.

## Rollback

Remove the author/publisher role assignments or disable access to the builder to stop new
control-plane mutations. Allow accepted test and production runs to finish from their immutable
snapshots. Stop selecting or deprecate a faulty non-default release, then explicitly select a
prior accepted version. Retain all drafts, revisions, artifacts, releases, grants, audits,
snapshots, conversations, and Temporal histories.
