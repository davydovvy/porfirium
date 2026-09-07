#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"

export TARGET_POSTGRES_ADMIN_PASSWORD=${TARGET_POSTGRES_ADMIN_PASSWORD:-verification-only}
export CONVERSATION_DB_PASSWORD=${CONVERSATION_DB_PASSWORD:-verification-only}
export REGISTRY_DB_PASSWORD=${REGISTRY_DB_PASSWORD:-verification-only}
export RUNNER_DB_PASSWORD=${RUNNER_DB_PASSWORD:-verification-only}
export RUNTIME_DB_PASSWORD=${RUNTIME_DB_PASSWORD:-verification-only}
export DELEGATION_DB_PASSWORD=${DELEGATION_DB_PASSWORD:-verification-only}
export CONFIGURATION_DB_PASSWORD=${CONFIGURATION_DB_PASSWORD:-verification-only}
export CHECKPOINT_DB_PASSWORD=${CHECKPOINT_DB_PASSWORD:-verification-only}
export RUN_CAPABILITY_SECRET=${RUN_CAPABILITY_SECRET:-verification-only}
export DELEGATION_SIGNING_SECRET=${DELEGATION_SIGNING_SECRET:-verification-only}
export REGISTRY_RESOLVER_TOKEN=${REGISTRY_RESOLVER_TOKEN:-verification-only}
export REGISTRY_RUN_PUBLIC_KEYS=${REGISTRY_RUN_PUBLIC_KEYS:-\{\}}
export RUNNER_DLQ_ENCRYPTION_KEY=${RUNNER_DLQ_ENCRYPTION_KEY:-MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=}
export OIDC_INTROSPECTION_URL=${OIDC_INTROSPECTION_URL:-http://keycloak.invalid/introspect}
export OIDC_TOKEN_URL=${OIDC_TOKEN_URL:-http://keycloak.invalid/token}
export OIDC_CLIENT_ID=${OIDC_CLIENT_ID:-verification-only}
export OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET:-verification-only}
export NATS_BOOTSTRAP_PASSWORD=${NATS_BOOTSTRAP_PASSWORD:-verification-only}
export NATS_CONVERSATION_PASSWORD=${NATS_CONVERSATION_PASSWORD:-verification-only}
export NATS_RUNNER_PASSWORD=${NATS_RUNNER_PASSWORD:-verification-only}
export NATS_RUNTIME_PASSWORD=${NATS_RUNTIME_PASSWORD:-verification-only}
export NATS_CHECKPOINT_PASSWORD=${NATS_CHECKPOINT_PASSWORD:-verification-only}
export NATS_REGISTRY_PASSWORD=${NATS_REGISTRY_PASSWORD:-verification-only}
export NATS_DELEGATION_PASSWORD=${NATS_DELEGATION_PASSWORD:-verification-only}
export NATS_CONFIGURATION_PASSWORD=${NATS_CONFIGURATION_PASSWORD:-verification-only}

docker compose --profile target -f "$compose_file" config --quiet

services=$(docker compose --profile target -f "$compose_file" config --services)
for required in \
  postgres nats nats-bootstrap registry otel-collector \
  portal-bff conversation-service agent-registry agent-runner agent-runtime-api \
  identity-delegation configuration-service checkpoint-api; do
  grep -qx "$required" <<<"$services" || {
    echo "missing target service: $required" >&2
    exit 1
  }
done

nats_config="$repo_dir/deploy/nats/nats.conf"
for identity in \
  bootstrap conversation_service agent_runner agent_runtime_api checkpoint_api \
  agent_registry identity_delegation configuration_service; do
  grep -q "user: $identity" "$nats_config" || {
    echo "missing NATS identity: $identity" >&2
    exit 1
  }
done

application_config=$(sed '/user: bootstrap/,/^    }/d' "$nats_config")
if grep -Eq 'publish: ">"|subscribe: ">"' <<<"$application_config"; then
  echo "an application NATS identity has unrestricted permissions" >&2
  exit 1
fi

for service in \
  portal-bff conversation-service agent-registry agent-runner agent-runtime-api \
  identity-delegation configuration-service checkpoint-api; do
  service_dir="$repo_dir/services/$service"
  for owned_file in pyproject.toml uv.lock Dockerfile tests/test_health.py; do
    test -f "$service_dir/$owned_file" || {
      echo "$service does not own $owned_file" >&2
      exit 1
    }
  done
done

test -x "$repo_dir/scripts/target-phase2/verify-nats.sh" || {
  echo "NATS integration verifier is not executable" >&2
  exit 1
}
test -x "$repo_dir/scripts/target-phase2/verify-durability.sh" || {
  echo "durability integration verifier is not executable" >&2
  exit 1
}
for verifier in verify-stack.sh acceptance.sh; do
  test -x "$repo_dir/scripts/target-phase2/$verifier" || {
    echo "$verifier is not executable" >&2
    exit 1
  }
done

ack_permission_count=$(grep -c '"\$JS.ACK.>"' "$repo_dir/deploy/nats/nats.conf")
test "$ack_permission_count" = 4 || {
  echo "expected acknowledgement permission for the four durable consumer identities" >&2
  exit 1
}

for stream in RUN_COMMANDS RUN_EVENTS CONVERSATION_EVENTS MESSAGE_DELTAS USER_INPUT AUDIT_EVENTS DEAD_LETTERS; do
  grep -q "ensure_stream $stream " "$repo_dir/deploy/nats/bootstrap.sh" || {
    echo "missing JetStream declaration: $stream" >&2
    exit 1
  }
done

for database in conversation registry runner runtime delegation configuration checkpoint; do
  grep -q " $database " "$repo_dir/deploy/postgres/init-service-databases.sh" || {
    echo "missing owned database: $database" >&2
    exit 1
  }
done

echo "Target Phase 2 infrastructure configuration verified."
