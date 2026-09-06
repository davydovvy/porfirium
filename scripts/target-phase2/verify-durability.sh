#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"
project_name="porfirium-durability-check-$$"
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

"${compose[@]}" up -d --wait postgres nats
"${compose[@]}" run --rm nats-bootstrap
"${compose[@]}" build agent-runner

"${compose[@]}" run --rm agent-runner python -m agent_runner.phase2_probe publish

# The event is durable in JetStream but not consumed when the server restarts.
"${compose[@]}" restart nats
"${compose[@]}" up -d --wait nats

# Commit the inbox and effect first, then exit without acknowledging. The restarted consumer must
# receive the redelivery, see the inbox record, and acknowledge without repeating the effect.
"${compose[@]}" run --rm agent-runner python -m agent_runner.phase2_probe consume-unacked
sleep 2
"${compose[@]}" run --rm agent-runner python -m agent_runner.phase2_probe consume-ack
"${compose[@]}" run --rm agent-runner python -m agent_runner.phase2_probe assert

echo "Outbox publication, NATS restart, consumer restart, and inbox deduplication verified."
