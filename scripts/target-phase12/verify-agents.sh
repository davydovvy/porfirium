#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

"$repo_dir/scripts/target-model-only/verify.sh"
"$repo_dir/scripts/target-planning-assistant/verify.sh"
"$repo_dir/scripts/target-planning-assistant/verify-tool.sh"

echo "PASS: two independently packaged target agents"
