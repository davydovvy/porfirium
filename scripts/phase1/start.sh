#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
./scripts/phase1/bootstrap.sh
docker compose up -d --build application-postgres portal-api portal
./scripts/phase1/status.sh
