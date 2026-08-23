# Increment 8 — Filesystem and CLI publication results

Status: Completed and accepted
Date: 2026-08-23

## Delivered

- strict schema-v2 declarative candidate loading from one version directory;
- canonical JSON artifacts with SHA-256 identity, 32 KiB bounds, immutable PostgreSQL storage,
  and database-enforced release/artifact digest agreement;
- one reusable publisher boundary for offline validation, platform resolution, atomic publication,
  idempotent retry, conflict handling, and read-only status;
- fail-closed resolution of enabled model aliases and unambiguous enabled read-only tool schemas;
- the `porfirium agents validate`, `publish`, and `status` CLI commands with stable JSON output;
- a read-only `/agents` control-plane mount on Portal API only; the agent worker has no source
  mount and execution continues from immutable acceptance snapshots;
- independently publishable `tool-assistant:1.3.0`, limited to the two unambiguous time tools;
- an operator runbook and Increment 8 verification script.

The MTG search stable name currently has two enabled schema versions. Filesystem publication
does not guess which is latest, so a schema-v2 candidate declaring that bare name fails as
ambiguous. The 1.3.0 canary intentionally uses only exact, unambiguous time-tool catalog entries.
A future manifest revision can add explicit tool schema selection without weakening this gate.

## Verification evidence

The following passed:

- backend Ruff and 40 Pytest tests;
- time MCP 6 tests and MTG catalog MCP 7 tests;
- frontend ESLint, 3 Vitest tests, TypeScript, and production Vite build;
- Compose rendering and secret-pattern scan;
- Increment 7 and Increment 8 static gates;
- additive live migration from `0008_versioned_tool_schema` to
  `0009_filesystem_publication`;
- offline and live platform validation of `tool-assistant:1.3.0`;
- initial publication followed by an identical idempotent retry returning the same release and
  publication identifiers;
- live status showing filesystem provenance, canonical artifact size/digest, model resolution,
  and both exact tool schema grants;
- one paid Yandex canary through `AgentRunWorkflow` completing an authorized time-tool call;
- explicit selection rollback by creating a new conversation pinned to accepted 1.2.0.

Live publication evidence:

```text
digest: sha256:303d82afbfa21de7dcd0a395e90d048c331fd46ec18ea8742bbe136dd9a8ccd4
artifact size: 634 bytes
release: d8c91c61-9e6a-45ea-9986-b4d0e9fae15c
publication: 9a90f9e6-08e8-42e5-a6ad-2bc90ea61448
canary turn: e62bc189-ca00-4ed5-b319-fd5df57a382e
rollback-selection conversation: 87b8d6f6-c4f3-48c8-b4e4-3dbf8e46b1cd
```

## Operation and rollback

Use [the Increment 8 runbook](INCREMENT8_RUNBOOK.md). Publication never changes the default
release. Roll back selection by choosing `tool-assistant:1.2.0` for a new conversation and allow
accepted 1.3.0 runs to finish. Do not mutate or delete releases, artifacts, grants, snapshots,
conversations, or Temporal histories.

## User acceptance

After the portal catalog was corrected to expand every published agent version rather than only
the server default, the user confirmed that 1.3.0 was visible and that everything worked. The
selector retains 1.2.0 as the default while allowing explicit 1.3.0 selection. Increment 8 was
accepted on 2026-08-23. Milestone M4 remains open until Increment 9 is delivered and accepted.
