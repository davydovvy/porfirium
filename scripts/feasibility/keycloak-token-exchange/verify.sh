#!/usr/bin/env bash
set -euo pipefail

gate_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
  "$gate_dir/probe.py"
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
  "$gate_dir/configure_and_probe.py"
python3 "$gate_dir/probe.py" --help >/dev/null
python3 "$gate_dir/configure_and_probe.py" --help >/dev/null

required=(
  KEYCLOAK_ISSUER
  KEYCLOAK_USER_CLIENT_ID
  KEYCLOAK_DELEGATION_CLIENT_ID
  KEYCLOAK_DELEGATION_CLIENT_SECRET
  KEYCLOAK_MCP_AUDIENCE
  KEYCLOAK_TEST_USERNAME
  KEYCLOAK_TEST_PASSWORD
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "FAIL: $name is required for the live feasibility gate" >&2
    exit 2
  fi
done

args=(
  --issuer "$KEYCLOAK_ISSUER"
  --user-client-id "$KEYCLOAK_USER_CLIENT_ID"
  --delegation-client-id "$KEYCLOAK_DELEGATION_CLIENT_ID"
  --delegation-client-secret "$KEYCLOAK_DELEGATION_CLIENT_SECRET"
  --mcp-audience "$KEYCLOAK_MCP_AUDIENCE"
  --username "$KEYCLOAK_TEST_USERNAME"
  --password "$KEYCLOAK_TEST_PASSWORD"
)
if [[ -n "${KEYCLOAK_CA_FILE:-}" ]]; then
  args+=(--ca-file "$KEYCLOAK_CA_FILE")
fi

python3 "$gate_dir/probe.py" "${args[@]}"
