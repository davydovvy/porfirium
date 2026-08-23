#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

cd "$repo_dir/services/time-mcp"
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run python -m unittest -v

cd "$repo_dir/services/mtg-catalog-mcp"
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run python -m unittest -v

cd "$repo_dir/apps/portal-api"
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run pytest

cd "$repo_dir/apps/web"
npm run lint
npm test
npm run build

cd "$repo_dir"
docker compose config --quiet
./scripts/phase1/secrets.sh
./scripts/increment7/verify.sh
