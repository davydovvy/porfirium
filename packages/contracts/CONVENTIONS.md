# Contract conventions

## HTTP

- Service-owned APIs use `/v1`; only the Portal BFF exposes browser-facing `/api/v1` routes.
- Mutating operations require `Idempotency-Key`, scoped to the authenticated caller and operation.
- `traceparent` carries W3C trace context and `X-Correlation-ID` carries a stable UUID.
- User identity is derived from validated credentials, never from a caller-supplied body field.
- Timestamps are UTC RFC 3339 values. Identifiers are UUIDs unless a contract says otherwise.

Errors use `application/problem+json` with the following stable fields:

```json
{
  "type": "https://porfirium.local/problems/idempotency-conflict",
  "title": "The idempotency key was reused with different input",
  "status": 409,
  "code": "idempotency_conflict",
  "correlation_id": "4cb7bfa4-5c1a-4d64-9e3d-23e44bc45933",
  "retryable": false
}
```

Safe bounded details may be added. Credentials, stack traces, provider payloads, prompts, tool
arguments, and checkpoint content are prohibited in errors.

## Idempotency

The owning service stores the caller, operation, key, canonical request digest, status, and result
reference in the same database as the affected entity. An exact replay returns the original
result. Reuse with a different digest returns `idempotency_conflict`. Keys are 8 to 128 printable
ASCII characters and must not contain credentials.

## Durable messages

Every JetStream payload validates against the canonical envelope and one event data schema.
Delivery is at least once. Producers use outboxes when publication accompanies a state change;
consumers use durable inbox records keyed by event ID. Ordering is only per aggregate.

The event `type` includes its schema major version. Consumers ignore unknown additive fields but
reject unsupported major versions. Dead-letter records contain identifiers and bounded safe error
metadata, never the original sensitive payload by default.

## Generated code

OpenAPI, Protocol Buffer, and JSON Schema sources are reviewed artifacts. Generation is
deterministic and pinned in CI. Services may consume generated DTOs and clients but do not share
domain entities, migrations, repositories, or writable database access.
