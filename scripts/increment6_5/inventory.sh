#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

active_turns=$(docker compose exec -T application-postgres psql -U genai -d genai -Atc \
  "SELECT count(*) FROM turns WHERE mode='agent' AND state IN ('accepted','running')")
if [[ "$active_turns" != "0" ]]; then
  docker compose exec -T application-postgres psql -U genai -d genai -P pager=off -c \
    "SELECT id, workflow_id, state, correlation_id, agent_run_snapshot_id FROM turns WHERE mode='agent' AND state IN ('accepted','running') ORDER BY created_at"
  echo "FAIL: $active_turns active Agent turn(s) remain" >&2
  exit 1
fi

temporal_json=$(mktemp)
pollers_json=$(mktemp)
cleanup() {
  rm -f "$temporal_json" "$pollers_json"
}
trap cleanup EXIT

docker compose exec -T temporal temporal workflow list \
  --address temporal:7233 \
  --namespace default \
  --query "ExecutionStatus='Running' AND (WorkflowType='PorfiriumAgentWorkflowV1' OR WorkflowType='PorfiriumToolAgentWorkflowV2')" \
  --output json >"$temporal_json"

python3 - "$temporal_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    executions = json.load(source)
if executions:
    for item in executions:
        execution = item.get("execution", {})
        print(
            "OPEN",
            execution.get("workflowId", "unknown"),
            execution.get("runId", "unknown"),
            item.get("type", "unknown"),
        )
    raise SystemExit(f"FAIL: {len(executions)} open legacy Temporal execution(s) remain")
PY

docker compose exec -T temporal temporal task-queue describe \
  --address temporal:7233 \
  --namespace default \
  --task-queue porfirium-agent-v1 \
  --task-queue-type workflow \
  --output json >"$pollers_json"

python3 - "$pollers_json" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone

with open(sys.argv[1], encoding="utf-8") as source:
    description = json.load(source)
pollers = description.get("pollers") or []
recent = []
cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
for poller in pollers:
    value = str(poller.get("lastAccessTime", ""))
    try:
        last_access = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        recent.append(poller)
        continue
    if last_access >= cutoff:
        recent.append(poller)
if recent:
    raise SystemExit(f"FAIL: {len(recent)} active legacy workflow poller(s) remain")
PY

echo "PASS: zero active Agent turns, open legacy executions, and legacy workflow pollers"
