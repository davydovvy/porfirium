#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

if rg -n --hidden \
  -g '!.env' -g '!.git/**' -g '!**/.venv/**' -g '!**/node_modules/**' -g '!**/dist/**' -g '!*.lock' \
  '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|sk-[A-Za-z0-9_-]{20,}|YANDEX_API_KEY=[A-Za-z0-9_-]{20,})' \
  .; then
  echo "Potential committed secret detected." >&2
  exit 1
fi
echo "Secret-pattern scan passed."
