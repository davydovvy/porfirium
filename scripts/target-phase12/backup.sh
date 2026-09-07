#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 NEW_BACKUP_DIRECTORY" >&2
  exit 2
fi

destination=$1
if [[ -e "$destination" ]]; then
  echo "backup destination already exists: $destination" >&2
  exit 2
fi
if [[ -z "${PORFIRIUM_BACKUP_KEYS_DIR:-}" || ! -d "$PORFIRIUM_BACKUP_KEYS_DIR" ]]; then
  echo "PORFIRIUM_BACKUP_KEYS_DIR must name the protected key bundle directory" >&2
  exit 2
fi

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
compose_file="$repo_dir/deploy/compose/target.yaml"
umask 077
mkdir -p "$destination/databases"

# Stop the data writers and volume owners for a coherent cross-system snapshot. PostgreSQL remains
# online for pg_dump. A host-managed Runner must be stopped separately and explicitly confirmed.
running_services=$(docker compose --profile target -f "$compose_file" ps \
  --status running --services)
if ! grep -qx agent-runner <<<"$running_services" \
  && [[ "${PORFIRIUM_HOST_RUNNER_STOPPED:-}" != true ]]; then
  echo "stop the host-managed Runner and set PORFIRIUM_HOST_RUNNER_STOPPED=true" >&2
  exit 2
fi
stop_services=()
for service in nats registry portal-bff conversation-service agent-registry agent-runner \
  agent-runtime-api identity-delegation configuration-service checkpoint-api; do
  if grep -qx "$service" <<<"$running_services"; then
    stop_services+=("$service")
  fi
done
cleanup() {
  if [[ ${#stop_services[@]} -gt 0 ]]; then
    docker compose --profile target -f "$compose_file" start "${stop_services[@]}" \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
docker compose --profile target -f "$compose_file" stop "${stop_services[@]}"

for database in conversation registry runner runtime delegation configuration checkpoint; do
  docker compose --profile target -f "$compose_file" exec -T postgres \
    pg_dump --username porfirium_admin --format custom --no-owner "$database" \
    >"$destination/databases/$database.dump"
done
docker compose --profile target -f "$compose_file" run --rm --no-deps --entrypoint tar nats \
  -C /data/jetstream -czf - . >"$destination/jetstream.tar.gz"
docker compose --profile target -f "$compose_file" run --rm --no-deps --entrypoint tar registry \
  -C /var/lib/registry -czf - . >"$destination/registry.tar.gz"
cleanup
trap - EXIT

tar -C "$PORFIRIUM_BACKUP_KEYS_DIR" -czf "$destination/protected-keys.tar.gz" .
cat >"$destination/RECOVERY_REQUIREMENTS.txt" <<'EOF'
Restore into empty service-owned databases and empty JetStream/registry volumes.
Restore protected signing and encryption keys before starting target services.
Supply deployment-managed database, NATS, OIDC, gateway, and operator secrets separately.
Run migrations, readiness checks, digest reconciliation, and the target acceptance gate before cutover.
EOF
(
  cd "$destination"
  sha256sum databases/*.dump jetstream.tar.gz registry.tar.gz protected-keys.tar.gz \
    >SHA256SUMS
)
echo "Backup written to $destination"
