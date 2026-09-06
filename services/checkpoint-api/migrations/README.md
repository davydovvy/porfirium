# Checkpoint API migrations

`0001_checkpoint_foundation.sql` owns immutable checkpoint versions, run-attempt fencing leases,
and scoped idempotency records. Apply migrations with:

```bash
python -m checkpoint_api.migrate
```

This directory is the service-owned ordered SQL migration chain. The migration runner records each
applied filename in `checkpoint_schema_migrations` and serializes concurrent migration attempts
with a PostgreSQL advisory lock. No other service may import its persistence models or write its
database.
