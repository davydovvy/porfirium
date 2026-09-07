#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
runner_dir="$repo_dir/services/agent-runner"
runtime_container=${RUNTIME_CONTAINER:-porfirium-agent-runtime-api}
runner_port=${TARGET_RUNNER_PORT:-18103}
runner_bind_host=${TARGET_RUNNER_BIND_HOST:-}

for command_name in podman uv; do
  command -v "$command_name" >/dev/null || {
    echo "missing required command: $command_name" >&2
    exit 1
  }
done

if [[ $(podman info --format '{{.Host.Security.Rootless}}') != true ]]; then
  echo "Runner requires a rootless Podman control plane" >&2
  exit 1
fi

podman container exists "$runtime_container" || {
  echo "Runtime container is not present in this user's Podman control plane: $runtime_container" >&2
  exit 1
}

if [[ -z $runner_bind_host || $runner_bind_host == 0.0.0.0 || $runner_bind_host == :: ]]; then
  echo "TARGET_RUNNER_BIND_HOST must be the rootless Podman bridge gateway address" >&2
  exit 1
fi

for variable_name in \
  DATABASE_URL NATS_URL NATS_USER NATS_PASSWORD AGENT_REGISTRY_URL \
  RUNNER_OIDC_TOKEN_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET \
  REGISTRY_RUN_PUBLIC_KEYS RUN_CAPABILITY_SECRET; do
  [[ -n ${!variable_name:-} ]] || {
    echo "missing required environment variable: $variable_name" >&2
    exit 1
  }
done

export AGENT_RUNTIME_URL=${AGENT_RUNTIME_URL:-runtime:50051}
export RUNTIME_CONTAINER="$runtime_container"
export CONTAINERS_REGISTRIES_CONF=${CONTAINERS_REGISTRIES_CONF:-$repo_dir/deploy/podman/registries.conf}
export UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT:-/tmp/porfirium-agent-runner-venv-$UID}

cd "$runner_dir"
exec uv run --frozen uvicorn agent_runner.main:app --host "$runner_bind_host" --port "$runner_port"
