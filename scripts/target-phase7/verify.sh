#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

run_suite() {
  local service=$1
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/services/${service},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/services/${service},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
}

run_suite configuration-service
run_suite identity-delegation
"$repo_dir/scripts/contracts/verify.sh"

echo "PASS: Phase 7 configuration, delegation, gateway policy, and redaction checks"
