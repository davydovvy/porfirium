#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
env_file="$repo_dir/.env"

"$repo_dir/scripts/phase0/bootstrap.sh"

if grep -q '^APPLICATION_POSTGRES_PASSWORD=' "$env_file"; then
  echo "Phase 1 environment already exists: $env_file"
  exit 0
fi

umask 077
printf 'APPLICATION_POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)" >>"$env_file"
echo "Added Phase 1 application credentials to $env_file without printing them."
