#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

cd "$repo_dir/apps/portal-api"
UV_CACHE_DIR=/tmp/genai-phase3-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/genai-phase3-uv-cache uv run pytest

cd "$repo_dir/apps/web"
npm run lint
npm test
npm run build

cd "$repo_dir"
docker compose config --quiet
./scripts/phase1/secrets.sh
./scripts/increment6_5/verify.sh
