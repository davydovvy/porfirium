#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

"$script_dir/verify.sh"
"$script_dir/verify-nats.sh"
"$script_dir/verify-durability.sh"
"$script_dir/verify-stack.sh"

echo "Target Phase 2 acceptance passed."
