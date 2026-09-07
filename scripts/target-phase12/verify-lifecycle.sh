#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

"$repo_dir/scripts/target-phase5/acceptance.sh"
docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/agent-runner,dst=/app,readonly" \
  --workdir /app "$uv_image" \
  uv run --isolated --frozen pytest -q tests/test_lifecycle.py

echo "PASS: Phase 12 cancellation and stale-lease lifecycle acceptance"
