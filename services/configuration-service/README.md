# Configuration Service

The Configuration Service owns immutable user and conversation configuration revisions. It
resolves effective configuration in the fixed order `release defaults <- user <- conversation`,
checks the Registry-provided JSON Schema and its SHA-256 digest, and returns a deterministic
effective revision ID and content digest. Plaintext secrets are not accepted; `secret_references`
are opaque, versioned references for their owning platform service.

Apply the service-owned migration before starting the API:

```bash
uv run python -m configuration_service.migrate
uv run uvicorn configuration_service.main:app --host 0.0.0.0 --port 8106
```

`DATABASE_URL` is required for the API and migration. Readiness also requires `NATS_URL`,
`NATS_USER`, and `NATS_PASSWORD`. Requests carry the authenticated owner identity in `X-User-ID`
at the internal service boundary and require `Idempotency-Key` on writes and resolution. The BFF
must derive that identity from verified claims; callers must never accept a browser-supplied owner
header directly.

Revisions are bounded to 64 KiB and 16 nested levels. Unknown fields, invalid types, schema digest
mismatches, cross-owner reads, incompatible releases/scopes, and idempotency-key reuse fail closed.

Run the focused suite from the repository root with `./scripts/target-phase7/verify.sh`.
