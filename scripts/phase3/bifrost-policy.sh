#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

config=$(curl -fsS http://127.0.0.1:8088/api/config)
if [[ $(jq -r '.client_config.mcp_disable_auto_tool_inject' <<<"$config") != "true" ]]; then
  jq '{client_config: (.client_config
      | .mcp_disable_auto_tool_inject = true
      | .log_retention_days = (if .log_retention_days < 1 then 30 else .log_retention_days end))}' \
    <<<"$config" \
    | curl -fsS -X PUT -H 'Content-Type: application/json' --data-binary @- \
        http://127.0.0.1:8088/api/config >/dev/null
fi

current=$(curl -fsS http://127.0.0.1:8088/api/config \
  | jq -r '.client_config.mcp_disable_auto_tool_inject')
if [[ "$current" != "true" ]]; then
  echo "Bifrost automatic MCP injection must be disabled for Phase 3" >&2
  exit 1
fi
echo "Bifrost deny-by-default MCP policy verified."
