#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
python3 "$repo_dir/scripts/increment6_5/smoke.py"
