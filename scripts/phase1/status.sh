#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"
docker compose ps application-postgres portal-api portal
printf '\nPortal:   https://portal.local:8444\n'
printf 'Keycloak: https://keycloak.local:8443\n'
