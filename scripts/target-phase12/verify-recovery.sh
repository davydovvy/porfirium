#!/usr/bin/env bash
set -euo pipefail

work_dir=$(mktemp -d)
container="porfirium-recovery-check-$$"
databases=(conversation registry runner runtime delegation configuration checkpoint)
cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT

docker run -d --name "$container" \
  -e POSTGRES_PASSWORD=recovery-check postgres:17.6-alpine >/dev/null
for _ in $(seq 1 30); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres >/dev/null
mkdir -p "$work_dir/backup/databases"
for database in "${databases[@]}"; do
  docker exec "$container" createdb -U postgres "$database"
  docker exec "$container" psql -U postgres -d "$database" -v ON_ERROR_STOP=1 -c \
    "CREATE TABLE recovery_probe(id integer PRIMARY KEY, value text NOT NULL); INSERT INTO recovery_probe VALUES (1, '$database-durable');" >/dev/null
  docker exec "$container" pg_dump -U postgres --format custom --no-owner "$database" \
    >"$work_dir/backup/databases/$database.dump"
done

mkdir -p "$work_dir/jetstream-source/streams" "$work_dir/registry-source/blobs" \
  "$work_dir/keys-source" "$work_dir/restored"
printf 'durable-consumer-state\n' >"$work_dir/jetstream-source/streams/state"
printf 'immutable-oci-blob\n' >"$work_dir/registry-source/blobs/sha256-probe"
printf 'publication-key-material\n' >"$work_dir/keys-source/registry-signing.key"
chmod 600 "$work_dir/keys-source/registry-signing.key"
tar -C "$work_dir/jetstream-source" -czf "$work_dir/backup/jetstream.tar.gz" .
tar -C "$work_dir/registry-source" -czf "$work_dir/backup/registry.tar.gz" .
tar -C "$work_dir/keys-source" -czf "$work_dir/backup/protected-keys.tar.gz" .
(
  cd "$work_dir/backup"
  sha256sum databases/*.dump jetstream.tar.gz registry.tar.gz protected-keys.tar.gz \
    >SHA256SUMS
  sha256sum --check SHA256SUMS >/dev/null
)
cp "$work_dir/backup/SHA256SUMS" "$work_dir/tampered-checksums"
cp "$work_dir/backup/registry.tar.gz" "$work_dir/tampered-registry.tar.gz"
printf 'tampered' >>"$work_dir/tampered-registry.tar.gz"
expected_registry_checksum=$(awk '$2 == "registry.tar.gz" {print $1}' \
  "$work_dir/tampered-checksums")
actual_registry_checksum=$(sha256sum "$work_dir/tampered-registry.tar.gz" | cut -d' ' -f1)
test "$actual_registry_checksum" != "$expected_registry_checksum"

for database in "${databases[@]}"; do
  docker exec "$container" dropdb -U postgres "$database"
  docker exec "$container" createdb -U postgres "$database"
  docker exec -i "$container" pg_restore -U postgres -d "$database" \
    <"$work_dir/backup/databases/$database.dump"
  value=$(docker exec "$container" psql -U postgres -d "$database" -Atc \
    "SELECT value FROM recovery_probe WHERE id=1")
  test "$value" = "$database-durable"
done

mkdir -p "$work_dir/restored/jetstream" "$work_dir/restored/registry" \
  "$work_dir/restored/keys"
tar -C "$work_dir/restored/jetstream" -xzf "$work_dir/backup/jetstream.tar.gz"
tar -C "$work_dir/restored/registry" -xzf "$work_dir/backup/registry.tar.gz"
tar -C "$work_dir/restored/keys" -xzf "$work_dir/backup/protected-keys.tar.gz"
cmp "$work_dir/jetstream-source/streams/state" \
  "$work_dir/restored/jetstream/streams/state"
cmp "$work_dir/registry-source/blobs/sha256-probe" \
  "$work_dir/restored/registry/blobs/sha256-probe"
cmp "$work_dir/keys-source/registry-signing.key" \
  "$work_dir/restored/keys/registry-signing.key"

echo "PASS: all seven service-owned database dumps restored with durable data"
echo "PASS: JetStream, OCI, and protected-key archives restored byte-for-byte"
echo "PASS: backup checksums verified and archive tampering was detected"
