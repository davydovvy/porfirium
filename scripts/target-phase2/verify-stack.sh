#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"
project_name="porfirium-stack-check-$$"
check_secret="phase2-$(date +%s)-$$"

export TARGET_POSTGRES_ADMIN_PASSWORD="$check_secret-admin"
export CONVERSATION_DB_PASSWORD="$check_secret-conversation-db"
export REGISTRY_DB_PASSWORD="$check_secret-registry-db"
export RUNNER_DB_PASSWORD="$check_secret-runner-db"
export RUNTIME_DB_PASSWORD="$check_secret-runtime-db"
export DELEGATION_DB_PASSWORD="$check_secret-delegation-db"
export CONFIGURATION_DB_PASSWORD="$check_secret-configuration-db"
export CHECKPOINT_DB_PASSWORD="$check_secret-checkpoint-db"
export RUN_CAPABILITY_SECRET="$check_secret-run-capability"
export NATS_BOOTSTRAP_PASSWORD="$check_secret-bootstrap"
export NATS_CONVERSATION_PASSWORD="$check_secret-conversation"
export NATS_RUNNER_PASSWORD="$check_secret-runner"
export NATS_RUNTIME_PASSWORD="$check_secret-runtime"
export NATS_CHECKPOINT_PASSWORD="$check_secret-checkpoint"
export NATS_REGISTRY_PASSWORD="$check_secret-registry"
export NATS_DELEGATION_PASSWORD="$check_secret-delegation"
export NATS_CONFIGURATION_PASSWORD="$check_secret-configuration"

compose=(docker compose -p "$project_name" --profile target -f "$compose_file")
services=(
  portal-bff conversation-service agent-registry agent-runner agent-runtime-api
  identity-delegation configuration-service checkpoint-api
)

cleanup() {
  "${compose[@]}" down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${compose[@]}" up -d --wait postgres nats registry otel-collector
"${compose[@]}" run --rm nats-bootstrap
"${compose[@]}" up -d --build --wait "${services[@]}"

for service in "${services[@]}"; do
  status=$("${compose[@]}" ps --format json "$service")
  grep -q '"Health":"healthy"' <<<"$status" || {
    echo "$service did not become healthy" >&2
    exit 1
  }
done

owners=(
  conversation_service agent_registry agent_runner agent_runtime
  identity_delegation configuration_service checkpoint_api
)
databases=(conversation registry runner runtime delegation configuration checkpoint)
passwords=(
  "$CONVERSATION_DB_PASSWORD" "$REGISTRY_DB_PASSWORD" "$RUNNER_DB_PASSWORD"
  "$RUNTIME_DB_PASSWORD" "$DELEGATION_DB_PASSWORD" "$CONFIGURATION_DB_PASSWORD"
  "$CHECKPOINT_DB_PASSWORD"
)

for index in "${!owners[@]}"; do
  owner=${owners[$index]}
  owned_database=${databases[$index]}
  foreign_index=$(((index + 1) % ${#databases[@]}))
  foreign_database=${databases[$foreign_index]}
  password=${passwords[$index]}

  "${compose[@]}" exec -T -e PGPASSWORD="$password" postgres \
    psql -h 127.0.0.1 -U "$owner" -d "$owned_database" -Atc 'SELECT 1' \
    | grep -qx 1

  if "${compose[@]}" exec -T -e PGPASSWORD="$password" postgres \
    psql -h 127.0.0.1 -U "$owner" -d "$foreign_database" -Atc 'SELECT 1' \
    >/dev/null 2>&1; then
    echo "$owner can connect to foreign database $foreign_database" >&2
    exit 1
  fi
done

echo "Full target startup, dependency readiness, and database ownership verified."
