#!/usr/bin/env bash
set -euo pipefail

[[ $# == 1 && -n $1 ]] || {
  echo "usage: $0 IMAGE" >&2
  exit 2
}

docker run --rm \
  --network none \
  --user 65532:65532 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16777216 \
  --cap-drop all \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 268435456 \
  --cpus 1 \
  --entrypoint /bin/sh \
  "$1" -eu -c '
    test "$(id -u)" = 65532
    test "$(id -g)" = 65532
    test "$(awk "/^CapEff:/ {print \$2}" /proc/self/status)" = 0000000000000000
    test "$(awk "/^NoNewPrivs:/ {print \$2}" /proc/self/status)" = 1
    test "$(awk "/^Seccomp:/ {print \$2}" /proc/self/status)" = 2
    test ! -e /var/run/docker.sock
    test ! -e /run/podman/podman.sock
    if touch /agent/escape-probe 2>/dev/null; then
      echo "agent root filesystem is writable" >&2
      exit 1
    fi
    printf "#!/bin/sh\nexit 0\n" > /tmp/escape-probe
    chmod 700 /tmp/escape-probe
    if /tmp/escape-probe 2>/dev/null; then
      echo "agent tmpfs permits execution" >&2
      exit 1
    fi
  '

echo "PASS: constrained image probe for $1"
