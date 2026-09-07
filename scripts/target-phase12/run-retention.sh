#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"

for service_module in \
  "conversation-service conversation_service.retention" \
  "agent-runtime-api agent_runtime_api.retention" \
  "checkpoint-api checkpoint_api.retention"; do
  read -r service module <<<"$service_module"
  docker compose --profile target -f "$compose_file" exec -T "$service" python -m "$module"
done

if docker compose --profile target -f "$compose_file" ps --status running --services \
  | grep -qx agent-runner; then
  docker compose --profile target -f "$compose_file" exec -T \
    agent-runner python -m agent_runner.retention
else
  echo "Runner is host-managed; run 'python -m agent_runner.retention' in its environment." >&2
fi
