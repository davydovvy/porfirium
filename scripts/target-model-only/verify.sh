#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
uv_image="ghcr.io/astral-sh/uv:0.8.13-python3.13-bookworm-slim"
agent_dir="$repo_dir/agents/model-only/1.0.1"
image="porfirium-model-only-verification:$$"

cleanup() {
  docker image rm --force "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --rm \
  --mount "type=bind,src=$repo_dir/packages/agent-sdk-python,dst=/app,readonly" \
  --workdir /app "$uv_image" \
  sh -c 'uv run --isolated --frozen ruff check --no-cache . && uv run --isolated --frozen pytest -q'

docker run --rm \
  --mount "type=bind,src=$repo_dir,dst=/repo,readonly" \
  --workdir /repo/agents/model-only/1.0.1 "$uv_image" \
  uv run --isolated --with /repo/packages/agent-sdk-python \
    --with pytest==8.4.2 --with pytest-asyncio==1.1.0 pytest -q

docker run --rm \
  --mount "type=bind,src=$agent_dir,dst=/app,readonly" \
  --workdir /app "$uv_image" uvx ruff==0.12.11 check --no-cache .

docker run --rm \
  --mount "type=bind,src=$repo_dir/scripts/target-model-only,dst=/app,readonly" \
  --workdir /app "$uv_image" \
  uv run --isolated --with cryptography==45.0.7 --with pytest==8.4.2 \
    pytest -q test_prepare_publication.py

docker run --rm \
  --mount "type=bind,src=$repo_dir/scripts/target-model-only,dst=/app,readonly" \
  --workdir /app "$uv_image" uvx ruff==0.12.11 check --no-cache .

python - "$agent_dir/manifest.template.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["apiVersion"] == "porfirium.ai/v1"
assert manifest["kind"] == "Agent"
assert manifest["metadata"]["name"] == "model-only"
assert manifest["metadata"]["version"] == "1.0.1"
assert manifest["spec"]["image"] == "${IMAGE}"
assert manifest["spec"]["sdk"] == ">=1.0.0,<2.0.0"
assert manifest["spec"]["models"] == ["default"]
assert manifest["spec"]["tools"] == []
PY

docker build --tag "$image" --file "$agent_dir/Dockerfile" "$repo_dir"
docker image inspect "$image" --format '{{json .Config.Entrypoint}}' | \
  grep -qx '\["python","-m","model_only_agent"\]'
"$repo_dir/scripts/target-phase12/probe-agent-image.sh" "$image"

echo "PASS: model-only release bootstrap, behavior, manifest, and OCI image"
