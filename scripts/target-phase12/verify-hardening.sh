#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

for project in services/agent-runner services/agent-runtime-api services/agent-registry; do
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
done

"$repo_dir/scripts/contracts/verify.sh"

grep -q 'porfirium.dlq.\*' "$repo_dir/deploy/nats/nats.conf"
grep -q 'RUNNER_MAX_CONCURRENT_RUNS' "$repo_dir/deploy/compose/target.yaml"
grep -q 'RUNNER_DLQ_ENCRYPTION_KEY' "$repo_dir/deploy/compose/target.yaml"
grep -q 'REGISTRY_ALLOWED_BUILDERS' "$repo_dir/deploy/compose/target.yaml"

echo "PASS: Phase 12 bounded failure, capacity, reconciliation, compatibility, and provenance checks"
