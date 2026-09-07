#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

"$repo_dir/scripts/target-phase12/verify-hardening.sh"
"$repo_dir/scripts/target-phase12/verify-agents.sh"
"$repo_dir/scripts/target-phase12/verify-lifecycle.sh"
"$repo_dir/scripts/target-phase12/verify-network-isolation.sh"

if [[ ${PHASE12_INCLUDE_RECOVERY:-false} == true ]]; then
  "$repo_dir/scripts/target-phase12/verify-recovery.sh"
else
  echo "INCOMPLETE: set PHASE12_INCLUDE_RECOVERY=true to run destructive restore acceptance" >&2
fi

if [[ ${PHASE12_INCLUDE_LIVE:-false} == true ]]; then
  "$repo_dir/scripts/target-phase12/acceptance.sh"
else
  echo "INCOMPLETE: set PHASE12_INCLUDE_LIVE=true to run credentialed live acceptance" >&2
fi

if [[ ${PHASE12_INCLUDE_RECOVERY:-false} != true || ${PHASE12_INCLUDE_LIVE:-false} != true ]]; then
  echo "Phase 12 local acceptance passed, but final acceptance is incomplete." >&2
  exit 2
fi

echo "PASS: complete Phase 12 acceptance baseline"
