# Checkpoint API

The service owns bounded, immutable, versioned checkpoint payloads. Agent processes authenticate
with signed run capabilities scoped to a thread, run, attempt, lease epoch, and read/write
operations; they never receive the service database credential.

Capabilities are bearer tokens signed with `RUN_CAPABILITY_SECRET`. Each token contains the
authorized thread, run, attempt, monotonically increasing lease epoch, expiry, and checkpoint
operations. Production issuance belongs to the Runner; the Phase 4 harness signs bounded fixture
capabilities only for local acceptance.

The HTTP surface follows `packages/contracts/openapi/checkpoint-api-v1.json`:

- `GET /v1/threads/{thread_id}/checkpoints`
- `GET /v1/threads/{thread_id}/checkpoints/{checkpoint_id}`
- `PUT /v1/threads/{thread_id}/checkpoints/{checkpoint_id}`

Writes require `Idempotency-Key`, the expected current thread version, payload serialization
version, and SHA-256 digest. Payloads are opaque to the service and limited to 1 MiB after base64
decoding.

Apply migrations with `python -m checkpoint_api.migrate`. The target Compose topology runs that
step before service startup. The full checkpoint and SDK gate is:

```bash
./scripts/target-phase4/acceptance.sh
```
