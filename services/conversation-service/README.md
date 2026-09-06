# Conversation Service

The service owns owner-scoped conversations, durable messages, input requests, presentation
ordering, and replay state. User messages atomically create a run intent in the transactional
outbox. Runtime message events are projected idempotently and completed content is validated from
its canonical bytes, chunk count, and SHA-256 digest.

For end-to-end completion, the service records Runtime result proposals and publishes
`porfirium.run.messages_committed.v1` only when every proposed final message is durably completed.
Proposal and message arrival order does not matter. The confirmation is transactional and stable
across publisher restarts; Runner remains the sole owner of terminal run state.

Apply migrations before startup with `python -m conversation_service.migrate`. Run focused gates
from the repository root:

```bash
./scripts/target-phase8/verify.sh
./scripts/target-phase9/verify.sh
```

Never renumber presentation events or reconstruct a completed message from retained deltas.
Input proposals remain in `reserved` state and are not presented until their matching suspension
commitment arrives. Replaying either event repairs partial saga state. Exactly one response changes
the request to `answered` and produces the checkpoint-bound resume intent.
