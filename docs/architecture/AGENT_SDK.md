# Porfirium Agent SDK contract

Status: accepted architecture contract

The Python SDK is the only supported platform integration for LangGraph agent application code.
It hides transport details while preserving explicit authorization, failure, and durability
semantics.

## Agent entrypoint

An agent image contains a manifest and importable LangGraph graph entrypoint. The runtime adapter
loads the graph, constructs the SDK context, restores the selected checkpoint, and invokes the graph
for one run activation.

Conceptual entrypoint:

```python
from porfirium import AgentContext

async def run(context: AgentContext) -> None:
    async for event in graph.astream_events(
        context.input,
        config=context.langgraph_config,
    ):
        await context.langgraph.publish(event)
```

Exact Python signatures belong to the versioned SDK protocol, but agents do not create platform
clients or parse credentials themselves.

## Public capabilities

```python
context.identity.user_id
context.config.get(...)
context.runtime.run_id
context.runtime.deadline
await context.runtime.cancelled()

await context.messages.send(...)
async with context.messages.stream(...) as message:
    await message.write(...)
await context.messages.request_input(...)

await context.llm.invoke(...)
context.llm.stream(...)

await context.tools.list()
await context.tools.invoke(...)

await context.checkpoints.get(...)
await context.checkpoints.put(...)
await context.checkpoints.list(...)

context.telemetry.span(...)
context.telemetry.generation(...)
```

The user ID is informational and comes from verified run context. It does not replace the delegated
token or grant access to arbitrary user data.

## Runtime channel

SDK opens one mutually authenticated or run-capability-authenticated gRPC bidirectional stream to
Agent Runtime API. Frames include protocol version, run/attempt/message identity, lease epoch,
sequence, idempotency key, trace context, and bounded typed payload. A superseded epoch is rejected
even if its container remains alive.

SDK persists enough local in-memory state to retransmit unacknowledged frames during the current
attempt. Runtime API deduplicates frames. Checkpoints, not the stream buffer, provide cross-attempt
recovery.

## Messages and LangGraph streaming

SDK maps supported LangGraph stream events to Porfirium messages. Model tokens are coalesced before
transmission. Unsupported graph events may become bounded diagnostic telemetry but never arbitrary
user-visible payloads.

A streaming context sends `started`, ordered deltas, then exactly one completion or interruption.
It accumulates bounded canonical content so completion can include the full content and hash.

SDK never silently retries generation after acknowledged visible output. It exposes a typed
interruption so graph policy or the user can decide whether to continue.

## Human input

`request_input` validates a UI-safe prompt and optional JSON schema, reserves a stable suspension
ID, commits the checkpoint and input request idempotently under that ID, waits for suspension-commit
acknowledgement, and then ends the activation. It does not keep the process or container blocked
awaiting a person.

The later user response is provided as the input of a new run restoring the referenced checkpoint.

## LLM access

SDK calls only the LLM Gateway with the run capability. It supplies the pinned model alias and may
request stricter limits but cannot select an ungranted model or increase limits. Streaming supports
cancellation and backpressure propagation to the provider request.

## MCP access

SDK sends the delegated user access token to the MCP Gateway and identifies the run/tool grant. It
does not decode, persist, log, checkpoint, or expose the token through the agent API. Token renewal
is requested through Runtime API and atomically replaces the in-memory credential.

Tool calls require stable invocation IDs. SDK retries only when the tool contract declares the
operation idempotent and no ambiguous result was observed.

## Checkpoints

SDK exposes a LangGraph checkpointer backed by State API. It supplies thread/run namespaces,
optimistic version, serialization version, and idempotency automatically. Payload and metadata are
bounded and must not contain platform credentials.

## Telemetry

SDK instruments graph nodes, model generations, tool calls, checkpoints, messages, and input waits
with OpenTelemetry. It emits OTLP to the platform Telemetry Collector, which exports to Langfuse.
Agent code receives no Langfuse credential.

Telemetry is asynchronous, bounded, sampled by policy, and non-fatal. Sensitive values are excluded
or redacted by default. Trace/span IDs correlate SDK activity with Runtime, Gateway, Runner, and
Conversation events.

## Error model

SDK errors have a stable code, safe message, retryability, correlation ID, and optional bounded
details. Categories include authentication, authorization, cancellation, deadline, validation,
transport, backpressure, model, tool, checkpoint conflict, input suspension, and platform
unavailability.

Authorization errors and ambiguous tool outcomes are never hidden. Automatic retry uses bounded
backoff, respects deadlines, and requires operation idempotency.

## Compatibility

Agent manifests declare an SDK semantic-version range and runtime protocol major version. Registry
rejects incompatible publication; Runner rejects incompatible admission. Additive protocol fields
are allowed within a major version. Breaking behavior requires a new major version and an explicit
compatibility window.

The SDK ships contract fixtures and a local harness that emulate Runtime, LLM, MCP, State, and
Telemetry APIs without granting infrastructure access.
