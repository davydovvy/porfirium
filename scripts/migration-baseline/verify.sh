#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

cd "$repo_dir"
python3 -m json.tool deploy/bifrost/config.json >/dev/null
python3 -m json.tool data/mtg/manifest.json >/dev/null
python3 -m py_compile \
  services/diagnostic-mcp/server.py \
  scripts/phase0/smoke.py \
  scripts/phase2/smoke.py \
  scripts/phase3/smoke.py \
  scripts/phase4/smoke.py
docker compose config --quiet
./scripts/phase1/secrets.sh
./scripts/phase3/bifrost-policy.sh

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

./scripts/phase0/smoke.sh
./scripts/phase2/smoke.sh
./scripts/phase3/smoke.sh
./scripts/phase4/smoke.sh

echo "PASS: complete Bifrost-era migration regression baseline"
