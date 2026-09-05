# Agent Registry

The Registry owns immutable agent releases and publication authorization. Apply its migrations with
`python -m agent_registry.migrate`; the target Compose stack runs this as `registry-migrate` before
starting the service.

`POST /v1/releases` is fail-closed until these settings are present:

- `OIDC_INTROSPECTION_URL`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET` configure OAuth token
  introspection. Tokens must be active, include the `agent-registry` audience (or
  `OIDC_AUDIENCE`), and carry the `genai-agent-publisher` role.
- `OCI_REGISTRY_URL` is the private Distribution API URL. `OCI_REGISTRY_HOST` is the exact host
  permitted in published image references.
- `REGISTRY_PUBLICATION_KEYS` is a JSON object mapping key IDs to base64-encoded raw 32-byte
  Ed25519 public keys.

The provenance signature covers canonical JSON (sorted keys and compact separators) containing
all provenance fields except `signature`. For example:

```json
{"builder":"ci.example","keyId":"ci-2026","subjectDigest":"sha256:..."}
```

CI signs those UTF-8 bytes with Ed25519 and sends the base64 signature. The Registry then verifies
the signature and independently confirms that the digest exists in the configured OCI registry.

Discovery evaluates the authenticated subject plus verified `groups` and role claims against
active grants. `discover`, `run`, and `admin` grants make an agent visible; publication rights do
not implicitly grant visibility. Grant creation and revocation require the distinct
`genai-agent-registry-admin` role and an `Idempotency-Key`.

Administrators select a published default through
`POST /v1/agents/{agent_id}/default-release`. The active default cannot be deprecated; select a
published replacement first, then call `POST /v1/releases/{release_id}:deprecate`. Deprecation is
irreversible and affects only future selection—stored release content and already-pinned consumers
remain unchanged.

Run-specification resolution requires a token with the `genai-agent-run-resolver` role and a
verified `porfirium_user_id` claim matching the request user. Configure the Registry-owned signing
key with `REGISTRY_RUN_SIGNING_KEY_FILE` (a file containing the base64 raw 32-byte Ed25519 private
key), `REGISTRY_RUN_SIGNING_KEY_ID`, and optionally
`REGISTRY_RUN_SPECIFICATION_TTL_SECONDS`. The corresponding public key belongs with the Runner;
the private key must remain a mounted secret available only to Registry.

Run the complete disposable Registry gate with:

```bash
./scripts/target-phase3/acceptance.sh
```

It builds and pushes independent OCI fixtures to a temporary Distribution registry and removes all
acceptance containers and volumes on exit.
