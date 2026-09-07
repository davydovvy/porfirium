#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"
agent_dir="$repo_dir/agents/planning-assistant/1.1.0"
image="porfirium-planning-tool-verification:$$"

cleanup() {
  docker image rm --force "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --rm \
  --mount "type=bind,src=$repo_dir,dst=/repo,readonly" \
  --workdir /repo/agents/planning-assistant/1.1.0 "$uv_image" \
  uv run --isolated --with /repo/packages/agent-sdk-python \
    --with pytest==8.4.2 --with pytest-asyncio==1.1.0 pytest -q
docker run --rm --mount "type=bind,src=$agent_dir,dst=/app,readonly" \
  --workdir /app "$uv_image" uvx ruff==0.12.11 check --no-cache .

python - "$agent_dir/manifest.template.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["metadata"]["name"] == "planning-assistant"
assert manifest["metadata"]["version"] == "1.1.0"
assert manifest["spec"]["tools"] == ["time_get_current_time"]
assert manifest["spec"]["models"] == ["default"]
PY

docker build --tag "$image" --file "$agent_dir/Dockerfile" "$repo_dir"
docker image inspect "$image" --format '{{json .Config.Entrypoint}}' | \
  grep -Fqx '["python","-m","planning_assistant"]'
"$repo_dir/scripts/target-phase12/probe-agent-image.sh" "$image"

echo "PASS: planning-assistant 1.1.0 declared-tool behavior and OCI image"
