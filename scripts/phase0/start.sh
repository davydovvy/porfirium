#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

./scripts/phase0/bootstrap.sh
docker compose pull
docker compose build diagnostic-mcp
docker compose up -d
docker compose ps

