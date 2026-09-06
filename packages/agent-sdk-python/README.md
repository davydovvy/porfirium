# Porfirium Agent SDK for Python

The SDK exposes immutable run identity and configuration, deadline enforcement, typed platform
errors, a bounded Checkpoint API client, and an async LangGraph checkpointer surface. It requires
only a short-lived run capability and never accepts database or NATS credentials.

```python
from porfirium_agent_sdk import CheckpointClient, LangGraphCheckpointer

client = CheckpointClient(
    base_url="http://checkpoint-api:8107",
    capability=run_capability,
    thread_id=thread_id,
    run_id=run_id,
    attempt_id=attempt_id,
    lease_epoch=lease_epoch,
)
checkpointer = LangGraphCheckpointer(client)
```

Use `CheckpointClient` as an async context manager or close it with `await client.aclose()`.
Platform failures raise `PlatformError` with a stable code, safe message, retryability flag,
correlation ID, and bounded details.
