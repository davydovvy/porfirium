#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
env_file="$repo_dir/.env"

for command_name in docker openssl; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required command: $command_name" >&2
    exit 1
  }
done

if [[ -f "$env_file" ]]; then
  echo "Phase 0 environment already exists: $env_file"
  exit 0
fi

secret() { openssl rand -hex 24; }
public_key="pk-lf-$(secret)"
secret_key="sk-lf-$(secret)"
langfuse_auth=$(printf '%s:%s' "$public_key" "$secret_key" | openssl base64 -A)

umask 077
{
  printf 'LANGFUSE_POSTGRES_PASSWORD=%s\n' "$(secret)"
  printf 'LANGFUSE_CLICKHOUSE_PASSWORD=%s\n' "$(secret)"
  printf 'LANGFUSE_REDIS_PASSWORD=%s\n' "$(secret)"
  printf 'LANGFUSE_MINIO_USER=phase0-minio\n'
  printf 'LANGFUSE_MINIO_PASSWORD=%s\n' "$(secret)"
  printf 'LANGFUSE_NEXTAUTH_SECRET=%s\n' "$(secret)"
  printf 'LANGFUSE_SALT=%s\n' "$(secret)"
  printf 'LANGFUSE_ENCRYPTION_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'LANGFUSE_INIT_USER_EMAIL=phase0@example.test\n'
  printf 'LANGFUSE_INIT_USER_NAME=Phase-0-Operator\n'
  printf 'LANGFUSE_INIT_USER_PASSWORD=%s\n' "$(secret)"
  printf 'LANGFUSE_INIT_PUBLIC_KEY=%s\n' "$public_key"
  printf 'LANGFUSE_INIT_SECRET_KEY=%s\n' "$secret_key"
  printf 'LANGFUSE_AUTH=Basic %s\n' "$langfuse_auth"
  printf 'YANDEX_API_KEY=replace-me\n'
  printf 'YANDEX_MODEL=gpt://replace-with-folder-id/deepseek-v4-flash/latest\n'
  printf 'YANDEX_OPENAI_BASE_URL=https://ai.api.cloud.yandex.net/v1\n'
} >"$env_file"

echo "Generated $env_file with mode 0600. Values were not printed."
