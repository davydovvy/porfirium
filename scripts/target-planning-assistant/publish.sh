#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
version=${PLANNING_ASSISTANT_VERSION:-1.1.0}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "PLANNING_ASSISTANT_VERSION must be a semantic version" >&2
  exit 1
}
agent_dir="$repo_dir/agents/planning-assistant/$version"
[[ -d $agent_dir ]] || {
  echo "planning-assistant package does not exist: $version" >&2
  exit 1
}
repository=${PLANNING_ASSISTANT_IMAGE_REPOSITORY:-${OCI_REGISTRY_HOST:-}/porfirium/planning-assistant}
tagged_image="$repository:$version"

for command_name in curl docker python uv; do
  command -v "$command_name" >/dev/null || {
    echo "missing required command: $command_name" >&2
    exit 1
  }
done
for variable_name in \
  OCI_REGISTRY_HOST AGENT_REGISTRY_URL REGISTRY_PUBLISH_TOKEN \
  REGISTRY_PUBLICATION_KEY_ID REGISTRY_PUBLICATION_PRIVATE_KEY_FILE; do
  [[ -n ${!variable_name:-} ]] || {
    echo "missing required environment variable: $variable_name" >&2
    exit 1
  }
done
[[ -f $REGISTRY_PUBLICATION_PRIVATE_KEY_FILE ]] || {
  echo "publication private key file does not exist" >&2
  exit 1
}

if [[ $REGISTRY_PUBLISH_TOKEN == client_credentials ]]; then
  for variable_name in RUNNER_OIDC_TOKEN_URL OIDC_CLIENT_ID OIDC_CLIENT_SECRET; do
    [[ -n ${!variable_name:-} ]] || {
      echo "missing required environment variable: $variable_name" >&2
      exit 1
    }
  done
  REGISTRY_PUBLISH_TOKEN=$(curl --fail-with-body --silent --show-error \
    --user "$OIDC_CLIENT_ID:$OIDC_CLIENT_SECRET" \
    --data 'grant_type=client_credentials' "$RUNNER_OIDC_TOKEN_URL" | \
    python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
fi

temporary_dir=$(mktemp -d)
cleanup() {
  rm -f "$temporary_dir/publication.json" "$temporary_dir/release.json" \
    "$temporary_dir/default.json"
  rmdir "$temporary_dir" 2>/dev/null || true
}
trap cleanup EXIT

docker build --provenance=false --tag "$tagged_image" --file "$agent_dir/Dockerfile" "$repo_dir"
docker push "$tagged_image"
digest=$(docker image inspect "$tagged_image" --format '{{json .RepoDigests}}' | \
  python -c 'import json,sys
repository=sys.argv[1]
matches=[item.rsplit("@", 1)[1] for item in json.load(sys.stdin) if item.rsplit("@", 1)[0] == repository]
print(matches[0] if matches else "")' "$repository")
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "registry did not return an immutable digest for $repository" >&2
  exit 1
}
image="$repository@$digest"

uv run --with cryptography==45.0.7 \
  "$repo_dir/scripts/target-model-only/prepare_publication.py" \
  --template "$agent_dir/manifest.template.json" \
  --image "$image" \
  --private-key-file "$REGISTRY_PUBLICATION_PRIVATE_KEY_FILE" \
  --key-id "$REGISTRY_PUBLICATION_KEY_ID" \
  --builder "${PLANNING_ASSISTANT_PUBLICATION_BUILDER:-porfirium-release}" \
  --output "$temporary_dir/publication.json"

version_key=${version//./-}
idempotency_key="planning-assistant-${version_key}-${digest:7:16}"
if ! curl --fail-with-body --silent --show-error \
  --request POST "$AGENT_REGISTRY_URL/v1/releases" \
  --header "Authorization: Bearer $REGISTRY_PUBLISH_TOKEN" \
  --header "Content-Type: application/json" \
  --header "Idempotency-Key: $idempotency_key" \
  --data-binary "@$temporary_dir/publication.json" \
  --output "$temporary_dir/release.json"; then
  python -c 'import json,sys
body=json.load(open(sys.argv[1]))
print(f"Publication rejected: {body.get('"'"'code'"'"', '"'"'unknown'"'"')} ({body.get('"'"'title'"'"', '"'"'no title'"'"')})", file=sys.stderr)' \
    "$temporary_dir/release.json"
  exit 1
fi

release_id=$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["release_id"])' \
  "$temporary_dir/release.json")

if [[ ${PLANNING_ASSISTANT_SET_DEFAULT:-false} == true ]]; then
  printf '{"release_id":"%s"}' "$release_id" >"$temporary_dir/default.json"
  curl --fail-with-body --silent --show-error \
    --request POST "$AGENT_REGISTRY_URL/v1/agents/planning-assistant/default-release" \
    --header "Authorization: Bearer $REGISTRY_PUBLISH_TOKEN" \
    --header "Content-Type: application/json" \
    --header "Idempotency-Key: planning-assistant-default-${release_id}" \
    --data-binary "@$temporary_dir/default.json" >/dev/null
fi

echo "Published planning-assistant $version as $image"
echo "Release ID: $release_id"
