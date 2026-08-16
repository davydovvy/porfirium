#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
docker compose stop portal portal-api bifrost diagnostic-mcp langfuse-web langfuse-worker application-postgres
