# Porfirium Agent SDK for Python

The SDK exposes immutable run identity and configuration, deadline enforcement, typed platform
errors, a bounded Checkpoint API client, an async LangGraph checkpointer, and reconnectable Runtime
message streaming. It requires only a short-lived run capability and never accepts database or
NATS credentials.

After `RuntimeClient.connect()`, `run_input` contains the immutable trigger snapshot authorized for
the attempt. User messages and human-input responses arrive through this field; agents do not read
Conversation Service or receive its credentials.

`request_input` uses one stable suspension ID to write a deterministic checkpoint, propose the
input request, commit both identities through Runtime API, and raise `InputSuspended`. Agent code
must let that exception end the activation; it must not wait in the container for a response.

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

Model calls use the same attempt-authenticated Runtime channel. The requested alias must be pinned
in the signed release; provider credentials and gateway topology never enter the agent:

```python
response = await runtime.model(str(runtime.run_input.value), model="default")
```

Stream an assistant message through Runtime with ordered, acknowledged deltas:

```python
from porfirium_agent_sdk import RuntimeClient

runtime = RuntimeClient(
    "agent-runtime-api:50051",
    run_id=run_id,
    attempt_id=attempt_id,
    lease_epoch=lease_epoch,
    run_capability=run_capability,
)
async with runtime.message() as message:
    await message.delta("Hello")
    await message.delta(" from Porfirium")
await runtime.close()
```

The context manager sends exactly one completion or interruption. Completion includes canonical
content, byte and chunk counts, and its SHA-256 digest. Unacknowledged frames remain in a bounded
in-memory buffer and are retransmitted after reconnect; checkpoints provide cross-attempt recovery.
