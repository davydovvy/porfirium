#!/usr/bin/env bash
set -euo pipefail

gate_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
venv_dir=${PORFIRIUM_LANGGRAPH_GATE_VENV:-/tmp/porfirium-langgraph-state-api-venv}
temp_dir=$(mktemp -d /tmp/porfirium-langgraph-state-api.XXXXXX)
state_pid=""

cleanup() {
  if [[ -n "$state_pid" ]]; then
    kill "$state_pid" >/dev/null 2>&1 || true
    wait "$state_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$temp_dir"
}
trap cleanup EXIT

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
if ! "$venv_dir/bin/python" -c \
  'import importlib.metadata; assert importlib.metadata.version("langgraph") == "1.2.11"' \
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
state_url="http://127.0.0.1:$port"
database="$temp_dir/state.db"
thread_id="feasibility-thread-$$"

start_state_api() {
  LANGGRAPH_STRICT_MSGPACK=true "$venv_dir/bin/python" "$gate_dir/state_api.py" \
    --database "$database" --port "$port" >"$temp_dir/state-api.log" 2>&1 &
  state_pid=$!
  for _ in $(seq 1 50); do
    if curl --fail --silent "$state_url/health/live" >/dev/null; then
      return
    fi
    sleep 0.1
  done
  echo "FAIL: State API did not become ready" >&2
  sed -n '1,120p' "$temp_dir/state-api.log" >&2
  exit 1
}

start_state_api
initial=$(LANGGRAPH_STRICT_MSGPACK=true "$venv_dir/bin/python" "$gate_dir/agent_process.py" \
  --state-api "$state_url" --thread-id "$thread_id")
grep -q '"__interrupt__"' <<<"$initial"
grep -q 'Allow the bounded operation' <<<"$initial"

kill "$state_pid"
wait "$state_pid" >/dev/null 2>&1 || true
state_pid=""
start_state_api

resumed=$(LANGGRAPH_STRICT_MSGPACK=true "$venv_dir/bin/python" "$gate_dir/agent_process.py" \
  --state-api "$state_url" --thread-id "$thread_id" --resume yes)
grep -q '"answer": "yes"' <<<"$resumed"
grep -q '"result": "approved:yes"' <<<"$resumed"

checkpoint_count=$(curl --fail --silent \
  "$state_url/v1/checkpoints?thread_id=$thread_id&namespace=" | \
  "$venv_dir/bin/python" -c 'import json, sys; print(len(json.load(sys.stdin)["items"]))')
if (( checkpoint_count < 2 )); then
  echo "FAIL: expected multiple durable checkpoints, found $checkpoint_count" >&2
  exit 1
fi
if rg -n '^(from sqlite3 import|import sqlite3)' \
  "$gate_dir/agent_process.py" "$gate_dir/http_checkpointer.py" >/dev/null; then
  echo "FAIL: agent-side code imports a database driver" >&2
  exit 1
fi
if rg -n 'add_argument\("--database' \
  "$gate_dir/agent_process.py" "$gate_dir/http_checkpointer.py" >/dev/null; then
  echo "FAIL: agent-side code contains a direct database dependency" >&2
  exit 1
fi

echo "PASS: LangGraph serialized $checkpoint_count checkpoints through the HTTP State API"
echo "PASS: interrupt survived State API restart and resumed in a second agent process"
echo "PASS: agent-side graph received no database path or credential"
