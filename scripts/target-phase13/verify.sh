#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
target_compose="$repo_dir/deploy/compose/target.yaml"
rootless_override="$repo_dir/deploy/compose/rootless-host-runner.yaml"
portal_url=${TARGET_PORTAL_URL:-https://portal.local:18444}
target_portal_port=${TARGET_PORTAL_PORT:-18444}
portal_resolve=${TARGET_PORTAL_RESOLVE:-portal.local:${target_portal_port}:127.0.0.1}
check_secret="phase13-compose-check"
export TARGET_PORTAL_PORT="$target_portal_port"

export TARGET_POSTGRES_ADMIN_PASSWORD=${TARGET_POSTGRES_ADMIN_PASSWORD:-$check_secret}
export CONVERSATION_DB_PASSWORD=${CONVERSATION_DB_PASSWORD:-$check_secret}
export REGISTRY_DB_PASSWORD=${REGISTRY_DB_PASSWORD:-$check_secret}
export RUNNER_DB_PASSWORD=${RUNNER_DB_PASSWORD:-$check_secret}
export RUNTIME_DB_PASSWORD=${RUNTIME_DB_PASSWORD:-$check_secret}
export DELEGATION_DB_PASSWORD=${DELEGATION_DB_PASSWORD:-$check_secret}
export CONFIGURATION_DB_PASSWORD=${CONFIGURATION_DB_PASSWORD:-$check_secret}
export CHECKPOINT_DB_PASSWORD=${CHECKPOINT_DB_PASSWORD:-$check_secret}
export RUN_CAPABILITY_SECRET=${RUN_CAPABILITY_SECRET:-$check_secret}
export DELEGATION_SIGNING_SECRET=${DELEGATION_SIGNING_SECRET:-$check_secret}
export REGISTRY_RUN_PUBLIC_KEYS=${REGISTRY_RUN_PUBLIC_KEYS:-'{}'}
export RUNNER_DLQ_ENCRYPTION_KEY=${RUNNER_DLQ_ENCRYPTION_KEY:-MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=}
export OIDC_INTROSPECTION_URL=${OIDC_INTROSPECTION_URL:-http://keycloak.invalid/introspect}
export OIDC_TOKEN_URL=${OIDC_TOKEN_URL:-http://keycloak.invalid/token}
export OIDC_CLIENT_ID=${OIDC_CLIENT_ID:-verification-only}
export OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET:-$check_secret}
export NATS_BOOTSTRAP_PASSWORD=${NATS_BOOTSTRAP_PASSWORD:-$check_secret}
export NATS_CONVERSATION_PASSWORD=${NATS_CONVERSATION_PASSWORD:-$check_secret}
export NATS_RUNNER_PASSWORD=${NATS_RUNNER_PASSWORD:-$check_secret}
export NATS_RUNTIME_PASSWORD=${NATS_RUNTIME_PASSWORD:-$check_secret}
export NATS_CHECKPOINT_PASSWORD=${NATS_CHECKPOINT_PASSWORD:-$check_secret}
export NATS_REGISTRY_PASSWORD=${NATS_REGISTRY_PASSWORD:-$check_secret}
export NATS_DELEGATION_PASSWORD=${NATS_DELEGATION_PASSWORD:-$check_secret}
export NATS_CONFIGURATION_PASSWORD=${NATS_CONFIGURATION_PASSWORD:-$check_secret}

compose_config=$(docker compose --profile target \
  -f "$target_compose" -f "$rootless_override" config --format json)

python3 -c '
import json
import os
import sys

config = json.load(sys.stdin)
portal = config["services"]["portal"]
assert portal["environment"]["PORTAL_API_UPSTREAM"] == "portal-bff:8100"
assert portal["cap_drop"] == ["ALL"]
assert portal["security_opt"] == ["no-new-privileges:true"]
assert portal["depends_on"] == {
    "portal-bff": {"condition": "service_healthy", "required": True}
}
assert portal["ports"] == [{
    "mode": "ingress",
    "target": 8444,
    "published": os.environ["TARGET_PORTAL_PORT"],
    "protocol": "tcp",
    "host_ip": "127.0.0.1",
}]
serialized = json.dumps(portal)
for legacy_dependency in ("portal-api", "temporal", "application-postgres"):
    assert legacy_dependency not in serialized
' <<<"$compose_config"

grep -Fq 'reverse_proxy {$PORTAL_API_UPSTREAM:portal-api:8000}' \
  "$repo_dir/apps/web/Caddyfile"
test "$(grep -Fc 'reverse_proxy {$PORTAL_API_UPSTREAM:portal-api:8000}' \
  "$repo_dir/apps/web/Caddyfile")" -eq 2
grep -Fq 'auto_https disable_redirects' "$repo_dir/apps/web/Caddyfile"
grep -Fq 'skip_install_trust' "$repo_dir/apps/web/Caddyfile"
grep -Fq 'RUN setcap -r /usr/bin/caddy' "$repo_dir/apps/web/Dockerfile"
grep -Fq '"https://portal.local:18444/*"' \
  "$repo_dir/scripts/target-keycloak/configure.py"
grep -Fq '"https://portal.local:18444"' \
  "$repo_dir/scripts/target-keycloak/configure.py"
grep -Fq 'attributes["post.logout.redirect.uris"] = "+"' \
  "$repo_dir/scripts/target-keycloak/configure.py"

(
  cd "$repo_dir/apps/web"
  npm run lint
  npm test
  npm run build
)

curl --fail --silent --show-error --insecure --resolve "$portal_resolve" \
  "$portal_url/health/ready" >/dev/null
curl --fail --silent --show-error --insecure --resolve "$portal_resolve" "$portal_url/" \
  | grep -Fq '<div id="root"></div>'
unauthenticated_status=$(curl --silent --show-error --insecure --resolve "$portal_resolve" \
  --output /dev/null --write-out '%{http_code}' "$portal_url/api/v1/agents")
test "$unauthenticated_status" = 401

echo "PASS: target portal configuration, frontend checks, HTTPS readiness, and API auth boundary"
