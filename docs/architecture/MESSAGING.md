# Messaging and response streaming

Status: accepted architecture contract

## Transport roles

- gRPC bidirectional streaming: Agent SDK to Agent Runtime API.
- HTTP/JSON: browser commands through the BFF and internal administrative APIs.
- SSE: ordered server-to-browser conversation updates.
- NATS JetStream: durable asynchronous commands and events between platform services.
- Core NATS: optional discardable presence signals only, never product state.

## Event envelope

All durable events use a CloudEvents-compatible envelope:

```json
{
  "specversion": "1.0",
  "type": "porfirium.message.delta.v1",
  "id": "event-uuid",
  "source": "agent-runtime-api",
  "subject": "conversation/conversation-uuid",
  "time": "RFC3339 timestamp",
  "user_id": "user-uuid",
  "conversation_id": "conversation-uuid",
  "thread_id": "thread-uuid",
  "run_id": "run-uuid",
  "attempt_id": "attempt-uuid",
  "lease_epoch": 3,
  "correlation_id": "correlation-uuid",
  "causation_id": "event-uuid",
  "traceparent": "W3C trace context",
  "schema_version": 1,
  "data": {}
}
```

Bearer tokens, secrets, raw configuration secrets, stack traces, and arbitrary environment values
are prohibited in every envelope.

## Streams

| Stream | Subjects | Retention intent |
|---|---|---|
| `RUN_COMMANDS` | `porfirium.run.command.*` | work queue |
| `RUN_EVENTS` | `porfirium.run.event.*` | durable lifecycle |
| `CONVERSATION_EVENTS` | `porfirium.conversation.event.*` | durable product events |
| `MESSAGE_DELTAS` | `porfirium.message.delta.*` | short reconnect window |
| `USER_INPUT` | `porfirium.input.command.*` | work queue |
| `AUDIT_EVENTS` | `porfirium.audit.event.*` | long-lived security evidence |
| `DEAD_LETTERS` | `porfirium.dlq.*` | bounded operator review |

Exact retention sizes and durations are deployment policy, not schema contracts.

## Delivery semantics

Delivery is at-least-once. There is no platform claim of end-to-end exactly-once delivery.

- Producers use a transactional outbox when persisting state and publishing an event constitute one
  business operation.
- Consumers use durable identities, explicit acknowledgement, inbox/deduplication records, bounded
  retry, and dead-letter handling.
- Commands require an idempotency key and identify the intended aggregate.
- Events are immutable facts and have globally unique event IDs.
- Ordering is guaranteed only within one aggregate stream.
- Consumers ignore unknown additive fields but reject unsupported schema major versions.
- Replaying an event cannot repeat a business side effect.

## Streaming path

```text
LLM Gateway -> SDK -> Runtime API -> JetStream -> Conversation Service -> BFF -> SSE -> Browser
```

The SDK consumes the model stream and coalesces tokens into deltas. It flushes on a bounded time or
byte threshold, explicit flush, or stream end. The initial policy should target 25–50 milliseconds
or 1–4 KiB; exact tuning is configuration.

The Runtime API validates each frame against the active run and attempt, then acknowledges it only
after durable acceptance. SDK reconnect identifies the run, message, and last acknowledged chunk.
Unacknowledged frames may be retransmitted and are deduplicated.

## Message protocol

One streaming response has a stable `message_id` and lifecycle:

```text
message.started -> message.delta* -> message.completed
                                \-> message.interrupted
                                \-> message.failed
```

A delta contains:

```json
{
  "message_id": "message-uuid",
  "chunk_sequence": 12,
  "content": "coalesced text fragment"
}
```

Completion contains:

```json
{
  "message_id": "message-uuid",
  "content": "complete canonical content",
  "chunk_count": 19,
  "content_bytes": 2841,
  "content_sha256": "hex digest",
  "finish_reason": "stop",
  "usage": {}
}
```

The complete canonical content is the durable assistant message. Deltas are short-lived delivery
artifacts. Conversation Service validates sequence, size, count, and final hash before committing
completion.

## Ordering

User-visible events contain two independent sequences:

- `conversation_sequence` orders presentation events in a conversation;
- `chunk_sequence` reconstructs one message.

Parallel LangGraph branches may produce separate messages with distinct IDs. They never write to
the same chunk sequence. Conversation Service allocates presentation order when it accepts events.

## Browser reconnect

The BFF exposes:

```text
GET /v1/conversations/{conversation_id}/events
Last-Event-ID: <conversation sequence>
```

SSE event IDs are conversation sequence values. On reconnect, the BFF first reads the authoritative
Conversation Service projection and then continues live delivery without a gap. A disconnected
browser never applies backpressure to an agent; the conversation projection continues independently.

Multiple BFF replicas do not share a queue consumer that would deliver an event to only one
replica. Each connection obtains replay from Conversation Service and may receive live invalidation
or fan-out signals without making those signals authoritative.

## Failure and retry

- Visible partial output is marked `interrupted`, never `completed`.
- A model generation is not transparently retried after visible content has been acknowledged.
- Recovery creates a new message ID from the last safe checkpoint.
- The first valid message terminal state wins.
- Deltas after a terminal state are rejected and audited.
- If Runtime API backpressure exceeds SDK buffer or deadline, SDK stops the upstream stream,
  requests checkpointing when safe, and returns a typed failure or suspension.
- Buffers are bounded by bytes, frames, and time in the SDK, Runtime API, JetStream, Conversation
  Service, BFF, and browser.

## Human input

`request_input` includes a stable request ID, prompt/schema, creation time, expiration policy, and
checkpoint reference. Conversation Service persists it before display. One authorized user
response becomes effective; duplicates return the original result. A valid response creates a new
run that resumes the thread. Expired, cancelled, already-answered, or foreign requests reject input.

Checkpoint and input-request creation use a `suspension_id` saga. The request becomes visible only
after State API confirms the referenced checkpoint. Repeated writes with the same suspension ID
return the existing result, and reconciliation repairs a crash between the two commits.

## Terminal precedence

Message completion and run completion are separate. A completed message remains valid if later
container cleanup fails. Runner may mark the run `completed` only after required message and
checkpoint acknowledgements. Conflicting late terminal events cannot overwrite the first valid
terminal transition.

Agent proposes a run result; it does not declare the authoritative run completion. Conversation
Service emits message-commit confirmation and State API emits checkpoint-commit confirmation.
Runner consumes those events, applies the pinned completion requirements, and publishes the sole
authoritative run terminal event. Missing confirmation enters bounded reconciliation.
