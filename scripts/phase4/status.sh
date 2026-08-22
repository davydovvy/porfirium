#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
docker compose ps application-postgres temporal temporal-ui portal-api agent-worker portal agentgateway diagnostic-mcp demo-time-mcp demo-mtg-catalog-mcp langfuse-web langfuse-worker
printf '\nPortal:       https://portal.local:8444\n'
printf 'Temporal:     http://localhost:8080\n'
printf 'Agentgateway: http://localhost:8089\n'
printf 'Langfuse:     http://localhost:3000\n'
printf 'Keycloak:     https://keycloak.local:8443\n'
