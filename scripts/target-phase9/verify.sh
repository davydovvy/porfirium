#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

for service in agent-runner conversation-service checkpoint-api; do
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/services/${service},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
done

docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/agent-runner,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/conversation-service,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/checkpoint-api,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen pytest -q tests/test_health.py
docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/checkpoint-api,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen pytest -q tests/test_api.py tests/test_auth.py

"$repo_dir/scripts/contracts/verify.sh"
echo "PASS: Phase 9 admission, confirmation convergence, cancellation, and recovery checks"
