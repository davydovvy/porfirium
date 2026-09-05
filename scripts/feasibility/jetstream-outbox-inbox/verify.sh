#!/usr/bin/env bash
set -euo pipefail

gate_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
venv_dir=${PORFIRIUM_NATS_GATE_VENV:-/tmp/porfirium-nats-gate-venv}
temp_dir=$(mktemp -d /tmp/porfirium-nats-gate.XXXXXX)
container="porfirium-nats-gate-$$"

cleanup() {
  podman rm --force "$container" >/dev/null 2>&1 || true
  rm -rf "$temp_dir"
}
trap cleanup EXIT

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
if ! "$venv_dir/bin/python" -c \
  'import importlib.metadata; assert importlib.metadata.version("nats-py") == "2.15.0"' \
  >/dev/null 2>&1; then
  "$venv_dir/bin/pip" install --requirement "$gate_dir/requirements.lock"
fi

port=$("$venv_dir/bin/python" -c '
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
')
podman run --detach --name "$container" --publish "127.0.0.1:$port:4222" \
  docker.io/library/nats:2.12-alpine -js >/dev/null

for _ in $(seq 1 100); do
  if podman logs "$container" 2>&1 | rg -q 'Server is ready'; then
    break
  fi
  sleep 0.1
done
podman logs "$container" 2>&1 | rg -q 'Server is ready'

"$venv_dir/bin/python" "$gate_dir/probe.py" \
  --server "nats://127.0.0.1:$port" --database "$temp_dir/business.db"
