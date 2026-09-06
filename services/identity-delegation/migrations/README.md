# Identity Delegation migrations

These ordered SQL migrations are applied by `python -m identity_delegation.migrate`. The initial
migration creates delegation grants and idempotency records. No other service may import this
service's persistence models or write its database.
