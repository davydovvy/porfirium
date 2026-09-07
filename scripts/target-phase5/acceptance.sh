#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
project_name="porfirium-phase5-acceptance-$$"
secret="phase5-$(date +%s)-$$"

export TARGET_POSTGRES_ADMIN_PASSWORD="$secret-admin"
export CONVERSATION_DB_PASSWORD="$secret-conversation-db"
export REGISTRY_DB_PASSWORD="$secret-registry-db"
export RUNNER_DB_PASSWORD="$secret-runner-db"
export RUNTIME_DB_PASSWORD="$secret-runtime-db"
export DELEGATION_DB_PASSWORD="$secret-delegation-db"
export CONFIGURATION_DB_PASSWORD="$secret-configuration-db"
export CHECKPOINT_DB_PASSWORD="$secret-checkpoint-db"
export RUN_CAPABILITY_SECRET="$secret-run-capability"
export DELEGATION_SIGNING_SECRET="$secret-delegation-signing"
export REGISTRY_RESOLVER_TOKEN="$secret-registry-resolver"
export REGISTRY_RUN_PUBLIC_KEYS="{}"
export RUNNER_DLQ_ENCRYPTION_KEY="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
export OIDC_INTROSPECTION_URL="http://keycloak.invalid/introspect"
export OIDC_TOKEN_URL="http://keycloak.invalid/token"
export OIDC_CLIENT_ID="verification-only"
export OIDC_CLIENT_SECRET="$secret-oidc"
export NATS_BOOTSTRAP_PASSWORD="$secret-bootstrap"
export NATS_CONVERSATION_PASSWORD="$secret-conversation"
export NATS_RUNNER_PASSWORD="$secret-runner"
export NATS_RUNTIME_PASSWORD="$secret-runtime"
export NATS_CHECKPOINT_PASSWORD="$secret-checkpoint"
export NATS_REGISTRY_PASSWORD="$secret-registry"
export NATS_DELEGATION_PASSWORD="$secret-delegation"
export NATS_CONFIGURATION_PASSWORD="$secret-configuration"
export USER_ID CONVERSATION_ID THREAD_ID RUN_ID ATTEMPT_ONE_ID ATTEMPT_TWO_ID MESSAGE_ID
readarray -t ids < <(python3 -c 'import uuid; print(*[uuid.uuid4() for _ in range(7)], sep="\n")')
USER_ID=${ids[0]}; CONVERSATION_ID=${ids[1]}; THREAD_ID=${ids[2]}; RUN_ID=${ids[3]}
ATTEMPT_ONE_ID=${ids[4]}; ATTEMPT_TWO_ID=${ids[5]}; MESSAGE_ID=${ids[6]}

compose=(docker compose -p "$project_name" --profile target
  -f "$repo_dir/deploy/compose/target.yaml" -f "$repo_dir/scripts/target-phase5/compose.yaml")
cleanup() { "${compose[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${compose[@]}" up -d --wait postgres nats
"${compose[@]}" run --rm nats-bootstrap
"${compose[@]}" up -d --wait agent-runtime-api
for mode in before-restart after-restart; do
  "${compose[@]}" run --rm --no-deps -e "HARNESS_MODE=$mode" -e USER_ID \
    -e CONVERSATION_ID -e THREAD_ID -e RUN_ID -e ATTEMPT_ONE_ID -e ATTEMPT_TWO_ID \
    -e MESSAGE_ID -e RUN_CAPABILITY_SECRET phase5-harness
  if [[ "$mode" == before-restart ]]; then
    "${compose[@]}" restart agent-runtime-api
    "${compose[@]}" up -d --wait agent-runtime-api
  fi
done
"${compose[@]}" run --rm --no-deps -e HARNESS_MODE=fence -e USER_ID -e CONVERSATION_ID \
  -e THREAD_ID -e RUN_ID -e ATTEMPT_ONE_ID -e ATTEMPT_TWO_ID -e MESSAGE_ID \
  -e RUN_CAPABILITY_SECRET phase5-harness

rows=$("${compose[@]}" exec -T postgres psql -U porfirium_admin -d runtime -Atc \
  "SELECT count(*) || ':' || count(DISTINCT event_id) FROM outbox_events")
[[ "$rows" == "4:4" ]] || { echo "unexpected/non-unique outbox events: $rows" >&2; exit 1; }
completion=$("${compose[@]}" exec -T postgres psql -U porfirium_admin -d runtime -Atc \
  "SELECT payload->'data'->>'content_sha256' FROM outbox_events WHERE payload->>'type'='porfirium.message.completed.v1'")
expected=$(printf 'restart safe' | sha256sum | cut -d' ' -f1)
[[ "$completion" == "$expected" ]] || { echo "final hash mismatch" >&2; exit 1; }

echo "Target Phase 5 Runtime API and message SDK acceptance passed."
