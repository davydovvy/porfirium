# Agent Runtime API

The Runtime API is the authenticated gRPC bridge between one agent attempt and Porfirium's durable
event backbone. It owns protocol frame delivery state and an event outbox; it does not own runs,
conversations, messages, or checkpoints.

Apply migrations with `python -m agent_runtime_api.migrate`. The HTTP health server listens on
8104 and the v1 gRPC service listens on 50051 by default. `RUN_CAPABILITY_SECRET` verifies bounded,
attempt-scoped capabilities. Agents receive only that capability and never database or NATS
credentials.

Run the disposable end-to-end gate from the repository root:

```bash
./scripts/target-phase5/acceptance.sh
```
