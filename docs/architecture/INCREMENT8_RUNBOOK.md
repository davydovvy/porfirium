# Increment 8 filesystem publication runbook

Status: Implemented; acceptance pending

The Portal API container exposes the operator-only `porfirium` CLI and mounts the repository
`agents/` directory read-only at `/agents`. The agent worker has no source mount. Publication
copies the canonical declarative artifact into PostgreSQL; execution never reads this mount.

## Validate and publish

Offline validation requires no database:

```bash
cd apps/portal-api
.venv/bin/porfirium agents validate ../../agents/tool-assistant/1.3.0 --json
```

Platform validation and publication run inside the Portal API container so they use its normal
database configuration:

```bash
docker compose exec portal-api .venv/bin/porfirium agents validate /agents/tool-assistant/1.3.0 --platform --json
docker compose exec portal-api .venv/bin/porfirium agents publish /agents/tool-assistant/1.3.0 --json
docker compose exec portal-api .venv/bin/porfirium agents status tool-assistant:1.3.0 --json
```

Repeating an identical publish is safe and returns `created: false`. Changed content under an
existing version fails with `release_version_conflict`; use a new semantic version.

Publication does not change the default. Select the version explicitly when creating a new Agent
conversation. Existing conversations and accepted run snapshots remain unchanged.

## Selection rollback

Create a new conversation selecting the previously accepted `tool-assistant:1.2.0` release.
Allow already accepted 1.3.0 runs to complete. Do not edit or delete either publication,
artifact, grants, snapshots, conversations, or Temporal histories.

## Verification

```bash
./scripts/increment8/verify.sh
./scripts/increment7/verify.sh
```

Moving or removing a version directory after publication does not affect the stored release.
Keep the repository package for reproducibility even though it is not a runtime dependency.
