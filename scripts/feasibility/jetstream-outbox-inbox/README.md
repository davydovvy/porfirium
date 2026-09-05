# JetStream outbox/inbox gate

Status: **accepted on NATS Server 2.12.15 / nats-py 2.15.0**

This gate runs a real NATS JetStream server and a service-owned SQLite transaction model. It proves
that due outbox rows publish, inbox uniqueness prevents duplicate business effects, invalid events
receive bounded retries and safe dead-letter records, and replay cannot repeat an effect.

```bash
./scripts/feasibility/jetstream-outbox-inbox/verify.sh
```

The verifier uses rootless Podman, NATS 2.12 Alpine, and `nats-py` 2.15.0. Its uniquely named NATS
container, database, and virtual environment state are isolated from the platform stack.

## Accepted observation

On 2026-09-05 the outbox published immediate and delayed rows to JetStream. A forced duplicate and
a full replay were both acknowledged without repeating either business effect. An invalid event was
negatively acknowledged until its third delivery, then acknowledged and represented in the durable
DLQ by only its event ID and safe error code; its raw payload was absent.

Decision: use transactional service-owned outboxes, explicit-ack durable consumers, and
service-owned inbox uniqueness constraints. Treat JetStream as at-least-once. Poison delivery is
bounded and produces a safe durable DLQ event; operator replay still passes through the inbox.
