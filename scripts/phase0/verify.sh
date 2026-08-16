#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

python3 -m json.tool deploy/bifrost/config.json >/dev/null
python3 -m json.tool data/mtg/manifest.json >/dev/null
python3 -m py_compile services/diagnostic-mcp/server.py scripts/phase0/smoke.py
docker compose config --quiet
echo "PASS static configuration and Python syntax checks"

if [[ "${1:-}" == "--skip-yandex" ]]; then
  PHASE0_SKIP_YANDEX=1 ./scripts/phase0/smoke.sh
else
  ./scripts/phase0/smoke.sh
fi

