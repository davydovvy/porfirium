# Increment 9 portal agent builder runbook

Status: Accepted operational procedure

## Access

Ordinary portal access still requires `genai-user`. Assign `genai-agent-author` to users who may
create, edit, validate, and privately test their own drafts. Assign
`genai-agent-publisher` separately to users who may review, publish, and deprecate releases.
`genai-admin` does not imply either role.

Restart the user's Keycloak session after changing realm roles so the access token contains the
new assignment. The API is the authorization boundary; hidden UI controls are not sufficient.

## Author workflow

1. Open **Agent builder** and create a structured declarative draft.
2. Save it to create immutable revision 1. Later saves require the displayed current revision
   and create the next immutable revision.
3. Validate the current revision. Validation resolves the configured model alias and requires
   every selected tool name to identify one enabled reviewed read-only schema.
4. Create a private test session and run one bounded test turn. The session is pinned to that
   revision and digest and runs on the existing generic Temporal worker.
5. If the draft changes, repeat validation and testing for the new revision.

Draft-test conversations are owner-only and excluded from the ordinary conversation and agent
catalog lists. Provider and tool calls are real; use synthetic prompts and the minimum calls
needed for acceptance.

## Publisher workflow

The publisher reviews the current manifest, digest, validation result, and successful test for
the exact revision. Publication repeats platform resolution inside the transaction and uses the
same publisher service as `porfirium agents publish`.

Publication is immutable and never changes an agent default. For a new agent with no default,
select its published version explicitly when creating a conversation. Repeating an identical
publication is safe; changing content under the same semantic version is a conflict.

Deprecation removes a non-default release from new selection. It does not change existing
conversations or accepted run snapshots. The API rejects deprecation of the current default
instead of choosing a replacement.

## Verification

```bash
./scripts/increment9/verify.sh
./scripts/increment8/verify.sh
```

For a live gate, record the draft, revision, digest, test turn, snapshot, workflow, release, and
publication IDs. Confirm the draft is absent from ordinary catalogs before publication and the
release appears without rebuilding the worker after publication.

## Rollback

Remove the author/publisher role assignments or roll back the builder UI to stop new control
plane actions. Allow accepted tests and production runs to finish from immutable snapshots.
Stop selecting or deprecate a faulty non-default release, then explicitly select a prior
published version. Do not delete or edit drafts, revisions, artifacts, grants, releases,
snapshots, conversations, audit rows, or Temporal histories, and do not downgrade past migration
`0010_portal_builder` while those rows are retained.
