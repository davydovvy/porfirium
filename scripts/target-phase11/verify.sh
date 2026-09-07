#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/portal-bff,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
docker run --rm \
  --mount "type=bind,src=${repo_dir}/services/portal-bff,dst=/app,readonly" \
  --workdir /app "$uv_image" uv run --isolated --frozen pytest -q

for project in packages/agent-sdk-python services/agent-runner services/agent-runtime-api \
  services/conversation-service; do
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen ruff check --no-cache .
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app "$uv_image" uv run --isolated --frozen pytest -q
done

(
  cd "$repo_dir/apps/web"
  npm run lint
  npm test
  npm run build
)

if grep -R -n -E 'Direct LLM|direct conversation|Temporal preserves' \
  "$repo_dir/apps/web/src"; then
  echo "FAIL: legacy execution mode remains in the target portal" >&2
  exit 1
fi

grep -q '"porfirium.run.command.requested"' "$repo_dir/deploy/nats/nats.conf" || {
  echo "FAIL: Conversation service cannot publish target run admission commands" >&2
  exit 1
}

"$repo_dir/scripts/contracts/verify.sh"

echo "PASS: Phase 11 BFF boundary, target conversations, SSE replay, and portal migration checks"
