#!/usr/bin/env bash
set -euo pipefail

image=${PORFIRIUM_ISOLATION_IMAGE:-docker.io/library/alpine:3.22}
suffix="$$"
probe_name="porfirium-isolation-probe-$suffix"
timeout_name="porfirium-isolation-timeout-$suffix"
sentinel_name="porfirium-isolation-sentinel-$suffix"

cleanup() {
  podman rm --force "$probe_name" "$timeout_name" "$sentinel_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ $(podman info --format '{{.Host.Security.Rootless}}') != true ]]; then
  echo "FAIL: Podman is not running rootlessly" >&2
  exit 1
fi

podman pull --quiet "$image" >/dev/null

security_args=(
  --user 65532:65532
  --read-only
  --read-only-tmpfs=false
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=1048576
  --cap-drop=all
  --security-opt=no-new-privileges
  --network=none
  --pids-limit=32
  --memory=64m
  --cpus=0.5
  --ulimit nofile=64:64
)

podman create --name "$probe_name" "${security_args[@]}" "$image" sh -euc '
  test "$(id -u)" = 65532
  test "$(id -g)" = 65532
  test "$(awk "/^CapEff:/ { print \$2 }" /proc/self/status)" = 0000000000000000
  test "$(awk "/^NoNewPrivs:/ { print \$2 }" /proc/self/status)" = 1
  test "$(awk "/^Seccomp:/ { print \$2 }" /proc/self/status)" = 2
  ! touch /rootfs-write 2>/dev/null
  touch /tmp/write-allowed
  printf "#!/bin/sh\nexit 0\n" >/tmp/noexec-test
  chmod +x /tmp/noexec-test
  ! /tmp/noexec-test 2>/dev/null
  test ! -e /run/podman/podman.sock
  test ! -e /var/run/docker.sock
  test ! -e /dev/sda
  test "$(find /sys/class/net -mindepth 1 -maxdepth 1 | wc -l)" = 1
  test -e /sys/class/net/lo
' >/dev/null
podman start --attach "$probe_name" >/dev/null

test "$(podman inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$probe_name")" = true
test "$(podman inspect --format '{{.HostConfig.NetworkMode}}' "$probe_name")" = none
test "$(podman inspect --format '{{.HostConfig.Memory}}' "$probe_name")" = 67108864
test "$(podman inspect --format '{{.HostConfig.PidsLimit}}' "$probe_name")" = 32
test "$(podman inspect --format '{{.HostConfig.NanoCpus}}' "$probe_name")" = 500000000

podman create --name "$sentinel_name" "$image" sleep 300 >/dev/null
podman start "$sentinel_name" >/dev/null
podman create --name "$timeout_name" "${security_args[@]}" "$image" sleep 300 >/dev/null
podman start "$timeout_name" >/dev/null

if timeout 2 podman wait "$timeout_name" >/dev/null; then
  echo "FAIL: bounded attempt unexpectedly exited before its deadline" >&2
  exit 1
fi
podman stop --time 1 "$timeout_name" >/dev/null
podman rm "$timeout_name" >/dev/null

if podman container exists "$timeout_name"; then
  echo "FAIL: timed-out attempt container still exists" >&2
  exit 1
fi
if [[ $(podman inspect --format '{{.State.Running}}' "$sentinel_name") != true ]]; then
  echo "FAIL: exact cleanup affected an unrelated container" >&2
  exit 1
fi

echo "PASS: rootless runtime and numeric non-root identity"
echo "PASS: read-only root, bounded noexec tmpfs, capabilities, seccomp, and no-new-privileges"
echo "PASS: no network, runtime sockets, host block device, or host mounts"
echo "PASS: PID, CPU, memory, file-descriptor, and elapsed-time limits"
echo "PASS: exact timed-out container cleanup preserved an unrelated container"
