#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

if docker compose config --services | grep -qx agent-worker; then
  echo "FAIL: legacy agent-worker remains in Compose" >&2
  exit 1
fi

if rg -n "TEMPORAL_TASK_QUEUE|porfirium-agent-v1|ToolAgentWorkflowV2|AgentWorkflowV1" \
  compose.yaml apps/portal-api/portal_api/main.py apps/portal-api/portal_api/config.py; then
  echo "FAIL: production legacy runtime reference remains" >&2
  exit 1
fi

config=$(curl -kfsS https://portal.local:8444/api/v1/config)
python3 -c 'import json,sys; assert json.load(sys.stdin)["agent_execution_mode"] == "maintenance"' <<<"$config"

python3 "$repo_dir/scripts/increment6_5/smoke.py"
"$repo_dir/scripts/increment6_5/inventory.sh"
echo "PASS: Increment 6.5 legacy runtime retirement gate"
