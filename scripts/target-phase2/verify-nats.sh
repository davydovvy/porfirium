#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"
project_name="porfirium-nats-check-$$"
check_secret="phase2-$(date +%s)-$$"

export TARGET_POSTGRES_ADMIN_PASSWORD="$check_secret"
export CONVERSATION_DB_PASSWORD="$check_secret"
export REGISTRY_DB_PASSWORD="$check_secret"
export RUNNER_DB_PASSWORD="$check_secret"
export RUNTIME_DB_PASSWORD="$check_secret"
export DELEGATION_DB_PASSWORD="$check_secret"
export CONFIGURATION_DB_PASSWORD="$check_secret"
export CHECKPOINT_DB_PASSWORD="$check_secret"
export RUN_CAPABILITY_SECRET="$check_secret-run-capability"
export DELEGATION_SIGNING_SECRET="$check_secret-delegation-signing"
export REGISTRY_RESOLVER_TOKEN="$check_secret-registry-resolver"
export REGISTRY_RUN_PUBLIC_KEYS="{}"
export NATS_BOOTSTRAP_PASSWORD="$check_secret-bootstrap"
export NATS_CONVERSATION_PASSWORD="$check_secret-conversation"
export NATS_RUNNER_PASSWORD="$check_secret-runner"
export NATS_RUNTIME_PASSWORD="$check_secret-runtime"
export NATS_CHECKPOINT_PASSWORD="$check_secret-checkpoint"
export NATS_REGISTRY_PASSWORD="$check_secret-registry"
export NATS_DELEGATION_PASSWORD="$check_secret-delegation"
export NATS_CONFIGURATION_PASSWORD="$check_secret-configuration"

compose=(docker compose -p "$project_name" --profile target -f "$compose_file")

cleanup() {
  "${compose[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${compose[@]}" up -d nats
"${compose[@]}" run --rm nats-bootstrap

stream_count=$(
  "${compose[@]}" exec -T nats \
    wget -qO- 'http://127.0.0.1:8222/jsz' \
    | sed -n 's/.*"streams": \([0-9][0-9]*\).*/\1/p'
)
test "$stream_count" = 7 || {
  echo "expected 7 streams, found ${stream_count:-none}" >&2
  exit 1
}

docker run --rm --network "${project_name}_default" natsio/nats-box:0.18.0 \
  nats --server nats://nats:4222 \
  --user conversation_service --password "$NATS_CONVERSATION_PASSWORD" \
  pub --jetstream porfirium.conversation.event.test '{}'

if docker run --rm --network "${project_name}_default" natsio/nats-box:0.18.0 \
  nats --server nats://nats:4222 \
  --user conversation_service --password "$NATS_CONVERSATION_PASSWORD" \
  pub --jetstream porfirium.run.command.start '{}' >/dev/null 2>&1; then
  echo "conversation-service cross-service publish was not denied" >&2
  exit 1
fi

echo "Authenticated NATS bootstrap and scoped publish permissions verified."
