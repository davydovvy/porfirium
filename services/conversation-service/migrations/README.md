# Conversation Service migrations

These ordered SQL migrations are applied by `python -m conversation_service.migrate`. The initial
migration creates owner-scoped conversation aggregates, canonical messages, transient chunks,
input requests, presentation events, request idempotency, and transactional inbox/outbox tables.
No other service may import this service's persistence implementation or write its database.

Migrations are forward-only in the target environment. Back up the `conversation` database before
schema changes. Do not roll back by deleting durable messages, presentation events, idempotency
records, or inbox rows; deploy a corrective forward migration instead.
