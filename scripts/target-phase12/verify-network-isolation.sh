#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

"$repo_dir/scripts/feasibility/runtime-only-network/verify.sh"

echo "PASS: Phase 12 deployment-network isolation acceptance"
