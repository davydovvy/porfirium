#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"

for project in services/agent-runner services/agent-runtime-api services/agent-registry \
  services/conversation-service services/checkpoint-api services/identity-delegation \
  services/portal-bff packages/agent-sdk-python; do
  docker run --rm \
    --mount "type=bind,src=${repo_dir}/${project},dst=/app,readonly" \
    --workdir /app --entrypoint /bin/sh "$uv_image" -c \
    'uv run --isolated --frozen ruff check --no-cache . && uv run --isolated --frozen pytest -q'
done

docker run --rm \
  --mount "type=bind,src=${repo_dir}/scripts/target-phase12,dst=/app,readonly" \
  --workdir /app "$uv_image" \
  uv run --isolated --with asyncpg==0.30.0 --with pytest==8.4.2 \
    pytest -q -p no:cacheprovider test_live_tool_acceptance.py

"$repo_dir/scripts/contracts/verify.sh"

grep -q 'porfirium.dlq.\*' "$repo_dir/deploy/nats/nats.conf"
grep -q 'RUNNER_MAX_CONCURRENT_RUNS' "$repo_dir/deploy/compose/target.yaml"
grep -q 'RUNNER_DLQ_ENCRYPTION_KEY' "$repo_dir/deploy/compose/target.yaml"
bash -n "$repo_dir/scripts/target-phase12/backup.sh"
bash -n "$repo_dir/scripts/target-phase12/run-retention.sh"
bash -n "$repo_dir/scripts/target-phase12/verify-recovery.sh"
bash -n "$repo_dir/scripts/target-phase12/verify-agents.sh"
bash -n "$repo_dir/scripts/target-phase12/verify-lifecycle.sh"
bash -n "$repo_dir/scripts/target-phase12/acceptance.sh"
bash -n "$repo_dir/scripts/target-phase12/probe-agent-image.sh"
bash -n "$repo_dir/scripts/target-phase12/verify-network-isolation.sh"
bash -n "$repo_dir/scripts/target-phase12/verify-acceptance.sh"
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
  "$repo_dir/scripts/target-phase12/live_tool_acceptance.py"
bash -n "$repo_dir/scripts/target-planning-assistant/publish.sh"
test -f "$repo_dir/agents/planning-assistant/1.1.0/manifest.template.json"
test -f "$repo_dir/agents/model-only/1.0.0/manifest.template.json"
test -f "$repo_dir/agents/planning-assistant/1.0.0/manifest.template.json"
grep -q 'REGISTRY_ALLOWED_BUILDERS' "$repo_dir/deploy/compose/target.yaml"
grep -q 'MCP_GATEWAY_URL' "$repo_dir/deploy/compose/target.yaml"

echo "PASS: Phase 12 failure, capacity, reconciliation, compatibility, provenance, retention, trace, and agent-package checks"
