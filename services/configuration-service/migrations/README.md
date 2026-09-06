# Configuration Service migrations

These ordered SQL migrations are applied by `python -m configuration_service.migrate`. The initial
migration creates immutable owner-scoped revisions and idempotency records. No other service may
import this service's persistence models or write its database.
