#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

cd "$repo_dir"
python3 -m json.tool data/mtg/manifest.json >/dev/null
python3 -m py_compile \
  services/diagnostic-mcp/server.py \
  scripts/agentgateway-spike/smoke.py \
  scripts/phase2/smoke.py \
  scripts/phase3/smoke.py \
  scripts/phase4/smoke.py
docker compose config --quiet
./scripts/phase1/secrets.sh

cd "$repo_dir/services/time-mcp"
UV_CACHE_DIR=/tmp/genai-migration-baseline-uv-cache uv run python -m unittest -v

cd "$repo_dir/services/mtg-catalog-mcp"
UV_CACHE_DIR=/tmp/genai-migration-baseline-uv-cache uv run python -m unittest -v

cd "$repo_dir/apps/portal-api"
UV_CACHE_DIR=/tmp/genai-migration-baseline-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/genai-migration-baseline-uv-cache uv run pytest

cd "$repo_dir/apps/web"
npm run lint
npm test
npm run build

cd "$repo_dir"
echo "PASS: migration baseline static, unit, component, and build checks"

./scripts/agentgateway-spike/verify.sh
./scripts/phase2/smoke.sh
./scripts/increment6_5/verify.sh

echo "PASS: migration regression and legacy-runtime retirement gate"
