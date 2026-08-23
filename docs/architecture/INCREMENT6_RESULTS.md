# Increment 6 implementation results

Date: 2026-08-23

Status: **Completed and accepted on 2026-08-23.**

Increment 6 adds the first versioned agent catalog without changing the visible behavior of the accepted Phase 4 Agent.

## Delivered

- Additive catalog migrations for agents, immutable published versions, drafts, publications, model aliases, tool catalog entries, per-version grants, and immutable run snapshots.
- The existing tool assistant packaged as `tool-assistant:1.0.0` with a strict JSON manifest and canonical digest `sha256:e67130e726d431e143d53c56244b18cad043683ab29273bee0112529d2317ec2`.
- Six explicit read-only tool grants and a bundled publication record with validation and provenance evidence.
- Read-only agent and version catalog APIs.
- Published-version selection during Agent conversation creation, with a server-resolved default for compatibility.
- Backfill of existing Agent conversations to the first published version; Direct conversations remain unpinned.
- A new immutable snapshot for every accepted Agent turn. The worker reads its instructions and granted tool set from that snapshot and rejects calls outside the pinned grants.
- An Agent version selector and pinned-version label in the portal.

Draft mutation and publication endpoints are intentionally not exposed yet. Increment 8 adds filesystem/CLI publication and Increment 9 adds portal authoring and publication.

## Verification evidence

- Backend Ruff and 28 tests pass, including manifest validity, digest stability, unknown-field rejection, and package-path identity checks.
- Frontend lint, component test, and production build pass.
- The migrations applied transactionally to the existing database at revision `0006_agent_immutable`.
- Database triggers reject published release-content deletion or mutation and published grant mutation. A deliberate digest mutation was rejected and the original digest remained intact.
- The seed contains one published version and six grants. All 68 pre-existing Agent conversations were backfilled, while all 20 Direct conversations remained unpinned.
- The complete Phase 4 verification passed against the migrated stack: worker-restart recovery, one-tool and ordered three-tool execution, audit/event persistence, cancellation, user isolation, Langfuse correlation, and unauthorized-tool denial.
- Four live acceptance Agent runs persisted snapshots with one immutable digest and all six granted tools.

The migration's first attempted live application encountered a SQLAlchemy bind-parser error in a JSON seed literal. PostgreSQL rolled the transaction back completely. The seed now uses an explicit JSON parameter; the corrected migration applied successfully.

## Acceptance

The user accepted Increment 6 on 2026-08-23 after the selected, pinned `tool-assistant:1.0.0` release preserved existing Agent behavior. Increment 7 has since introduced the generic version-neutral Temporal workflow and the declarative `tool-assistant:1.1.0` compatibility release; `1.0.0` remains immutable historical catalog data.
