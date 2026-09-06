#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"
acceptance_compose_file="$repo_dir/scripts/target-phase4/compose.yaml"
project_name="porfirium-phase4-acceptance-$$"
check_secret="phase4-$(date +%s)-$$"

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
export THREAD_ID RUN_ID ATTEMPT_ONE_ID ATTEMPT_TWO_ID CHECKPOINT_ONE_ID CHECKPOINT_TWO_ID
readarray -t ids < <(python3 -c 'import uuid; print(*[uuid.uuid4() for _ in range(6)], sep="\n")')
THREAD_ID=${ids[0]}
RUN_ID=${ids[1]}
ATTEMPT_ONE_ID=${ids[2]}
ATTEMPT_TWO_ID=${ids[3]}
CHECKPOINT_ONE_ID=${ids[4]}
CHECKPOINT_TWO_ID=${ids[5]}

compose=(
  docker compose -p "$project_name" --profile target
  -f "$compose_file" -f "$acceptance_compose_file"
)
cleanup() { "${compose[@]}" down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${compose[@]}" up -d --wait postgres nats checkpoint-api
for mode in write resume; do
  "${compose[@]}" run --rm --no-deps \
    -e "HARNESS_MODE=$mode" -e THREAD_ID -e RUN_ID -e ATTEMPT_ONE_ID -e ATTEMPT_TWO_ID \
    -e CHECKPOINT_ONE_ID -e CHECKPOINT_TWO_ID -e RUN_CAPABILITY_SECRET \
    phase4-harness
done

echo "Target Phase 4 Checkpoint API and SDK acceptance passed."
