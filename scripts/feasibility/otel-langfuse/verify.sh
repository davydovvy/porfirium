#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
gate_dir="$repo_dir/scripts/feasibility/otel-langfuse"
venv_dir=${PORFIRIUM_OTEL_GATE_VENV:-/tmp/porfirium-otel-gate-venv}

cleanup() {
  docker compose -f "$repo_dir/compose.yaml" -f "$gate_dir/compose.yaml" \
    stop feasibility-otel-collector >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
if ! "$venv_dir/bin/python" -c \
  'import importlib.metadata; assert importlib.metadata.version("opentelemetry-sdk") == "1.44.0"' \
  >/dev/null 2>&1; then
  "$venv_dir/bin/pip" install --requirement "$gate_dir/requirements.lock"
fi

cd "$repo_dir"
./scripts/phase0/bootstrap.sh
docker compose -f compose.yaml -f "$gate_dir/compose.yaml" up -d \
  langfuse-postgres langfuse-clickhouse langfuse-minio langfuse-redis \
  langfuse-worker langfuse-web feasibility-otel-collector

sdk_traceparent=$(env -i PATH="$PATH" \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 \
  "$venv_dir/bin/python" "$gate_dir/emitter.py" --role sdk)
gateway_traceparent=$(env -i PATH="$PATH" \
  OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 \
  "$venv_dir/bin/python" "$gate_dir/emitter.py" --role gateway --parent "$sdk_traceparent")

trace_id=${sdk_traceparent:3:32}
test "${gateway_traceparent:3:32}" = "$trace_id"
"$venv_dir/bin/python" "$gate_dir/query.py" --trace-id "$trace_id" --env-file "$repo_dir/.env"

if env -i PATH="$PATH" OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 env | \
  rg -q 'LANGFUSE|AUTH|SECRET|PUBLIC_KEY'; then
  echo "FAIL: attempt-side telemetry environment contains a Langfuse credential" >&2
  exit 1
fi
echo "PASS: SDK and gateway emitters held no Langfuse credential"
