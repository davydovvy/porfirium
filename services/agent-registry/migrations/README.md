# Agent Registry migrations

These ordered SQL migrations are applied only to the Registry-owned database during target stack
bootstrap. No other service may import its persistence code or write these tables.

- `0001_registry_foundation.sql` creates immutable releases, agent metadata, access grants,
  append-only publication and access-grant audit, immutable signed run specifications, and
  operation-scoped idempotency records.
