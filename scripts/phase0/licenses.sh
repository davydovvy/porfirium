#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo_dir"

echo "Configured images and resolved local digests:"
docker compose config --images | while IFS= read -r image; do
  digest=$(docker image inspect "$image" --format '{{join .RepoDigests ","}}' 2>/dev/null || true)
  printf '%-70s %s\n' "$image" "${digest:-not-pulled}"
done
echo
echo "Human-reviewed license decisions: docs/phase0/LICENSES.md"

