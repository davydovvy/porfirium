#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

for variable_name in KEYCLOAK_TOKEN_URL AGENT_REGISTRY_URL PORTAL_BFF_URL \
  RUNTIME_DATABASE_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET TEST_USER_CLIENT_ID \
  TEST_USERNAME TEST_PASSWORD TEST_OTHER_USERNAME TEST_OTHER_PASSWORD; do
  [[ -n ${!variable_name:-} ]] || {
    echo "missing required environment variable: $variable_name" >&2
    exit 2
  }
done

if [[ ${PHASE12_PREFLIGHT_ONLY:-false} != true \
  && ${PHASE12_PUBLISH_AGENTS:-${PHASE12_PUBLISH_AGENT:-false}} == true ]]; then
  MODEL_ONLY_SET_DEFAULT=true "$repo_dir/scripts/target-model-only/publish.sh"
  PLANNING_ASSISTANT_VERSION=1.1.0 PLANNING_ASSISTANT_SET_DEFAULT=true \
    "$repo_dir/scripts/target-planning-assistant/publish.sh"
fi

preflight_arguments=()
if [[ ${PHASE12_PREFLIGHT_ONLY:-false} == true ]]; then
  preflight_arguments+=(--preflight-only)
fi

uv run --isolated --with asyncpg==0.30.0 \
  "$repo_dir/scripts/target-phase12/live_tool_acceptance.py" \
  --keycloak-token-url "$KEYCLOAK_TOKEN_URL" \
  --registry-url "$AGENT_REGISTRY_URL" \
  --bff-url "$PORTAL_BFF_URL" \
  --runtime-database-url "$RUNTIME_DATABASE_URL" \
  --service-client-id "$OIDC_CLIENT_ID" \
  --service-client-secret "$OIDC_CLIENT_SECRET" \
  --registry-audience "${AGENT_REGISTRY_AUDIENCE:-agent-registry}" \
  --user-client-id "$TEST_USER_CLIENT_ID" \
  --username "$TEST_USERNAME" \
  --password "$TEST_PASSWORD" \
  --other-username "$TEST_OTHER_USERNAME" \
  --other-password "$TEST_OTHER_PASSWORD" \
  "${preflight_arguments[@]}"
