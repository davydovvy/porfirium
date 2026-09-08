# Offline cutover preparation

Phase 13 moves new conversations to the target platform. Preserve Keycloak identities and publish
selected agents as signed, digest-pinned target releases. Do not import legacy conversations,
messages, runs, checkpoints, or Temporal history. This document prepares the operation; no legacy
freeze, traffic switch, or retirement has been performed.

## Decisions to record before execution

| Decision | Required record | Current state |
| --- | --- | --- |
| Agent selection | Legacy agent ID, target release ID/digest, owner, grants, models/tools | Pending owner selection; model-only 1.0.1 and planning-assistant 1.1.1 are acceptance packages |
| Identity mapping | Keycloak realm, stable subject IDs, roles and target access grants | Two distinct test users verified; full user/role inventory pending |
| Traffic switch | Public endpoint, routing component, exact change and reversal | Pending deployment-specific routing inventory |
| Maintenance window | Operator, approver, freeze time and drain deadline | Pending scheduling |
| Rollback window | Duration, rollback owner, health criteria and retention deadline | Pending agreement |
| Backup location | Protected storage, encryption/key custody and restore evidence | Pending actual legacy backup; disposable target restore gate is separate evidence |

Keep credentials, provider payloads and production data out of this document and Git. Record only
identifiers and protected evidence locations.

## Preparation sequence

1. Inventory the active legacy Compose deployment, Portal API, worker, Temporal namespace,
   databases, artifact storage and Keycloak dependencies. Identify the actual traffic-routing
   configuration and capture a reversible configuration change before scheduling maintenance.
2. Select agents with their owners. Map each to a signed target release and digest, configuration,
   model aliases, tool grants, and eligible users. The two acceptance packages do not by themselves
   establish that every legacy agent has a replacement.
3. Reconcile identity and ownership using stable Keycloak subjects. Verify target release visibility
   and run access for allowed users, and hidden resources for unauthorized users.
4. Rehearse backups and restores in an isolated environment. The target backup procedure is in
   [Operations](OPERATIONS.md#target-backup-and-restore). Capture actual legacy database, artifact,
   Temporal and protected-key backups as well; the disposable Phase 12 restore is not a legacy
   backup. Confirm the retained legacy stack can be recovered independently of target writes.
5. Prepare exact freeze, drain, switch and rollback commands for the inventoried deployment.
   Review them before execution. Confirm stopping new admissions does not prevent active workflows
   from draining, and define handling for runs that exceed the drain deadline.

## Execution gates

- Before freezing: selected replacements, ownership mapping, routing reversal and maintenance
  responsibilities are recorded; baseline tests pass against the intended deployment.
- Before switching: legacy authoring and new conversations are frozen, active Temporal workflows
  are drained, actual backups are verified, and target signed releases and grants are reconciled.
- After switching: start fresh target conversations and run the full acceptance gate with both
  live and recovery checks enabled. Verify durable Runner completion, message/checkpoint
  confirmations, delegated tool execution, isolation and authorization. Target UI must not expose
  legacy history.
- During the rollback window: retain legacy databases and Temporal history read-only. A rollback
  routes traffic to the retained legacy stack under the agreed admission policy; target writes
  remain separate and are not reverse-synchronized. Preserve target state for investigation.
- Before retirement: the rollback window has ended, target acceptance and backup/restore evidence
  remain valid, and the owner authorizes retirement. Only then remove Temporal and legacy runtime
  infrastructure.

## Remaining follow-up

Preserve sanitized attempt exit status before container cleanup to improve future diagnostics.
This is distinct from the verified completion handshake and does not replace cutover rehearsal.
