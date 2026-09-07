#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
overlay="$repo_dir/deploy/compose/rootless-host-runner.yaml"

grep -q 'location = "localhost:15000"' "$repo_dir/deploy/podman/registries.conf"
grep -q 'CONTAINERS_REGISTRIES_CONF' "$repo_dir/scripts/target-runner/start-host.sh"
launcher="$repo_dir/scripts/target-runner/start-host.sh"

grep -q 'container_name: porfirium-agent-runtime-api' "$overlay"
grep -q '127.0.0.1:${TARGET_POSTGRES_PORT:-15432}:5432' "$overlay"
grep -q '127.0.0.1:${TARGET_NATS_PORT:-14222}:4222' "$overlay"
grep -q '127.0.0.1:${TARGET_REGISTRY_PORT:-18102}:8102' "$overlay"
grep -q 'AGENT_RUNNER_URL: http://host.containers.internal:' "$overlay"

grep -q "podman info --format '{{.Host.Security.Rootless}}'" "$launcher"
grep -q 'podman container exists "$runtime_container"' "$launcher"
grep -q 'AGENT_RUNTIME_URL=${AGENT_RUNTIME_URL:-runtime:50051}' "$launcher"
grep -q 'TARGET_RUNNER_BIND_HOST must be the rootless Podman bridge gateway address' "$launcher"
if grep -q -- '--host 0.0.0.0' "$launcher"; then
  echo "FAIL: host Runner listens on a wildcard address" >&2
  exit 1
fi

if grep -R -n -E 'podman.sock|docker.sock|/var/run' "$overlay" "$launcher"; then
  echo "FAIL: host Runner topology exposes a container runtime socket" >&2
  exit 1
fi

echo "PASS: host Runner topology is rootless, runtime-pinned, and socket-free"
