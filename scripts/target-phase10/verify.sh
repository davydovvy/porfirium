#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"
projects=(packages/agent-sdk-python services/agent-runner services/conversation-service)

for project in "${projects[@]}"; do
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
done

"$repo_dir/scripts/contracts/verify.sh"
echo "PASS: Phase 10 stable suspension, saga repair, single response, and resume checks"
