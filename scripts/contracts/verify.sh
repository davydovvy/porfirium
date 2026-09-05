#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

python3 scripts/contracts/verify.py
python3 scripts/contracts/compatibility.py
python3 scripts/contracts/generate.py --check
