#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

services=$(docker compose config --services)
test "$(grep -cx agent-worker <<<"$services")" -eq 1

rg -q 'TEMPORAL_AGENT_RUN_TASK_QUEUE: porfirium-agent-runtime-v1' compose.yaml
rg -q '@workflow.defn\(name="AgentRunWorkflow"\)' apps/portal-api/portal_api/agent.py
rg -q 'workflows=\[AgentRunWorkflow\]' apps/portal-api/portal_api/worker.py

if rg -n 'porfirium-agent-v1|PorfiriumToolAgentWorkflowV2|PorfiriumAgentWorkflowV1' \
  compose.yaml apps/portal-api/portal_api/agent.py apps/portal-api/portal_api/worker.py; then
  echo "FAIL: production legacy runtime reference remains" >&2
  exit 1
fi

test -f agents/tool-assistant/1.1.0/manifest.json
test -f apps/portal-api/migrations/versions/0007_generic_agent_runtime.py
test -f agents/tool-assistant/1.2.0/manifest.json
test -f apps/portal-api/migrations/versions/0008_versioned_tool_schema.py

echo "PASS: Increment 7 generic runtime static gate"
