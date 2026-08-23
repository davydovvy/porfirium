#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

test -f docs/architecture/INCREMENT8_PLAN.md
test -f agents/tool-assistant/1.3.0/manifest.json
test -f apps/portal-api/migrations/versions/0009_filesystem_publication.py
rg -q 'porfirium = "portal_api.cli:main"' apps/portal-api/pyproject.toml
rg -q 'provenance: str = "filesystem"' apps/portal-api/portal_api/publisher.py
compose_config=$(docker compose config)
rg -q 'target: /agents' <<<"$compose_config"
rg -q 'read_only: true' <<<"$compose_config"

cd apps/portal-api
.venv/bin/python -m portal_api.cli agents validate ../../agents/tool-assistant/1.3.0 --json
.venv/bin/ruff check .
.venv/bin/pytest -q

echo "PASS: Increment 8 filesystem publication static and unit gate"
