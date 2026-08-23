#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
docker compose stop portal portal-api temporal-ui temporal agentgateway diagnostic-mcp demo-time-mcp demo-mtg-catalog-mcp langfuse-web langfuse-worker application-postgres
