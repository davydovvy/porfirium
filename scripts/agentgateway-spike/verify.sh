#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image="cr.agentgateway.dev/agentgateway@sha256:771afaf093065477fa296eb90dcb618a0300165f12a32f80bbdd1427fab900ec"

cd "$repo_dir"
python3 -m py_compile scripts/agentgateway-spike/smoke.py
docker compose config --quiet
docker run --rm --entrypoint /app/agentgateway \
  --env-file "$repo_dir/.env" \
  -v "$repo_dir/deploy/agentgateway/config.yaml:/config/config.yaml:ro" \
  "$image" -f /config/config.yaml --validate-only
docker compose up -d --build diagnostic-mcp demo-time-mcp demo-mtg-catalog-mcp agentgateway-spike
python3 -u scripts/agentgateway-spike/smoke.py
