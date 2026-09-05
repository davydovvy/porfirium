#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
gate_dir="$repo_dir/scripts/feasibility/grpc-reconnect"
venv_dir=${PORFIRIUM_GRPC_GATE_VENV:-/tmp/porfirium-grpc-gate-venv}
temp_dir=$(mktemp -d /tmp/porfirium-grpc-reconnect.XXXXXX)
server_pid=""
client_pid=""

cleanup() {
  [[ -z "$client_pid" ]] || kill "$client_pid" >/dev/null 2>&1 || true
  [[ -z "$server_pid" ]] || kill "$server_pid" >/dev/null 2>&1 || true
  rm -rf "$temp_dir"
}
trap cleanup EXIT

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
if ! "$venv_dir/bin/python" -c \
  'import importlib.metadata; assert importlib.metadata.version("grpcio") == "1.83.1"' \
  >/dev/null 2>&1; then
  "$venv_dir/bin/pip" install --requirement "$gate_dir/requirements.lock"
fi

generated="$temp_dir/generated"
mkdir -p "$generated"
"$venv_dir/bin/python" -m grpc_tools.protoc \
  -I "$repo_dir/packages/contracts/protobuf" \
  --python_out="$generated" \
  --grpc_python_out="$generated" \
  "$repo_dir/packages/contracts/protobuf/porfirium/runtime/v1/runtime.proto"

port=$("$venv_dir/bin/python" -c '
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
')
export PYTHONPATH="$generated"
state="$temp_dir/state.json"

"$venv_dir/bin/python" "$gate_dir/server.py" \
  --port "$port" --state "$state" --crash-after 2 >"$temp_dir/server-1.log" 2>&1 &
server_pid=$!
sleep 0.3
"$venv_dir/bin/python" "$gate_dir/client.py" --target "127.0.0.1:$port" \
  >"$temp_dir/client.log" 2>&1 &
client_pid=$!

set +e
wait "$server_pid"
first_status=$?
set -e
server_pid=""
if [[ $first_status -ne 70 ]]; then
  echo "FAIL: first Runtime API did not crash at the injected boundary" >&2
  exit 1
fi

"$venv_dir/bin/python" "$gate_dir/server.py" --port "$port" --state "$state" \
  >"$temp_dir/server-2.log" 2>&1 &
server_pid=$!
wait "$client_pid"
client_pid=""

"$venv_dir/bin/python" -c '
import json, pathlib, sys
state = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert state["accepted"] == [1, 2, 3, 4], state
assert state["attempts"]["2"] >= 2, state
' "$state"
cat "$temp_dir/client.log"
echo "PASS: sequence 2 was retransmitted and deduplicated after Runtime API restart"
echo "PASS: durable accepted sequence is exactly [1, 2, 3, 4]"
