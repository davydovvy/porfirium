#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
./scripts/phase1/bootstrap.sh
docker compose up -d --build application-postgres temporal temporal-ui diagnostic-mcp demo-time-mcp demo-mtg-catalog-mcp langfuse-web langfuse-worker agentgateway
docker compose up -d --build portal-api agent-worker portal
./scripts/phase4/status.sh
