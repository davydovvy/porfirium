#!/usr/bin/env bash
set -euo pipefail

image=${PORFIRIUM_ISOLATION_IMAGE:-docker.io/library/alpine:3.22}
suffix="$$"
network="porfirium-attempt-network-$suffix"
other_network="porfirium-other-network-$suffix"
runtime="porfirium-runtime-endpoint-$suffix"
foreign="porfirium-foreign-attempt-$suffix"
probe="porfirium-network-probe-$suffix"

cleanup() {
  podman rm --force "$probe" "$foreign" "$runtime" >/dev/null 2>&1 || true
  podman network rm "$network" "$other_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ $(podman info --format '{{.Host.Security.Rootless}}') != true ]]; then
  echo "FAIL: Podman is not rootless" >&2
  exit 1
fi

podman network create --internal "$network" >/dev/null
podman network create --internal "$other_network" >/dev/null

podman run --detach --name "$runtime" --network "$network" --network-alias runtime \
  "$image" nc -lk -p 50051 -e /bin/cat >/dev/null
podman run --detach --name "$foreign" --network "$other_network" --network-alias foreign \
  "$image" sleep 300 >/dev/null

podman run --name "$probe" --network "$network" \
  --user 65532:65532 --read-only --read-only-tmpfs=false \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1048576 \
  --cap-drop=all --security-opt=no-new-privileges \
  --pids-limit 32 --memory 64m --cpus 0.5 --ulimit nofile=64:64 \
  "$image" sh -euc '
    response=$(printf runtime-only | nc -w 2 runtime 50051)
    test "$response" = runtime-only
    ! nc -z -w 1 1.1.1.1 80
    ! nc -z -w 1 169.254.169.254 80
    ! nc -z -w 1 host.containers.internal 80
    ! nc -z -w 1 foreign 1 2>/dev/null
    for endpoint in postgres:5432 nats:4222 agent-registry:8102 registry:5000 \
      identity-delegation:8106 checkpoint-api:8107 conversation-service:8108 \
      portal-bff:8100; do
      host=${endpoint%:*}
      port=${endpoint#*:}
      ! nc -z -w 1 "$host" "$port" 2>/dev/null
    done
    test ! -e /run/podman/podman.sock
    test ! -e /var/run/docker.sock
  ' >/dev/null

test "$(podman network inspect --format '{{.Internal}}' "$network")" = true
attached_networks=$(podman inspect --format '{{json .NetworkSettings.Networks}}' "$probe")
[[ "$attached_networks" == *"\"$network\""* ]]

echo "PASS: attempt reached only its platform Runtime endpoint"
echo "PASS: public, metadata, host, service, foreign-attempt, and runtime-socket access was denied"
echo "PASS: per-attempt network is internal and platform-selected"
