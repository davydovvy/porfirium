#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

test -f docs/ARCHITECTURE.md
test -f docs/OPERATIONS.md
test -f apps/portal-api/migrations/versions/0010_portal_agent_builder.py
rg -q 'genai-agent-author' apps/portal-api/portal_api/authoring.py
rg -q 'genai-agent-publisher' apps/portal-api/portal_api/authoring.py
rg -q 'PublicationContext\("portal"' apps/portal-api/portal_api/authoring.py
rg -q 'AgentRunWorkflow.run' apps/portal-api/portal_api/authoring.py
rg -q 'AgentBuilder' apps/web/src/App.tsx

cd apps/portal-api
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/genai-phase4-uv-cache uv run pytest -q

cd ../web
npm run lint
npm test -- --run
npm run build

echo "PASS: Increment 9 portal authoring static and unit gate"
