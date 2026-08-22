#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

python3 -m json.tool data/mtg/manifest.json >/dev/null
python3 -m py_compile services/diagnostic-mcp/server.py scripts/agentgateway-spike/smoke.py
docker compose config --quiet
echo "PASS static configuration and Python syntax checks"
./scripts/agentgateway-spike/verify.sh
