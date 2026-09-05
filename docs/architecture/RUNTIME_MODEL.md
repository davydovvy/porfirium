# Runtime model

Status: accepted architecture contract

This document defines execution identity and lifetime. These terms are stable across the Portal,
Registry, Runner, SDK, State API, and event schemas.

## Identity hierarchy

```text
User
  └── Conversation
      └── LangGraph thread
          ├── Run
          │   ├── Attempt 1 -> container
          │   └── Attempt 2 -> container, only after safe recovery
          └── Run
              └── Attempt 1 -> container
```

- A **conversation** is durable user-facing history bound to one immutable agent release.
- A **thread** is the LangGraph checkpoint namespace for that conversation.
- A **run** is one bounded graph activation caused by one user message, user response, or explicit
  resume action.
- An **attempt** is one container execution for a run.
- A **container** belongs to exactly one attempt and is never reused.
- An **input request** is a durable suspension point correlated with a future user response.

One conversation normally maps to one thread and contains many runs. The identifiers remain
separate so future workflows can use more than one thread without changing run contracts.

## Run lifecycle

```text
requested -> accepted -> scheduled -> starting -> running
                                             |       |
                                             |       +-> suspending -> waiting_for_input
                                             |       +-> completed
                                             |       +-> failed
                                             |       +-> cancelling -> cancelled
                                             +----------> failed
```

Terminal states are `completed`, `failed`, and `cancelled`. `waiting_for_input` is durable but not
terminal for the conversation or thread. It is terminal for the current container attempt.

At a human-input boundary the agent must:

1. reserve one stable `suspension_id` through SDK;
2. persist the LangGraph checkpoint idempotently under that suspension ID;
3. create the input request idempotently with the same ID and checkpoint reference;
4. publish `run.suspension_committed` after both services acknowledge durability;
5. end the attempt and allow Runner to revoke credentials and remove the container.

Checkpoint and input-request writes cannot share a database transaction. Their common suspension
ID, idempotent operations, and a reconciliation state machine form a saga. A reconciler completes
or safely abandons reservations left by crashes. An input request is not displayed until its
checkpoint exists, and a response cannot start a run until suspension is committed.

The user response is stored exactly once against the input-request ID and creates a new run. That
run restores the referenced checkpoint and continues the same thread in a new container.

No container remains alive merely to wait for a person.

## Admission snapshot

Run admission pins:

- user, conversation, thread, run, and triggering input IDs;
- agent identity, release, manifest, and OCI digest;
- SDK and runtime protocol versions;
- effective non-secret configuration, schema/revision digests, and opaque secret references;
- revocable non-secret delegation grant ID for attempt-time MCP token exchange;
- model and tool grants;
- resource, time, byte, call, and retry limits;
- checkpoint namespace and starting checkpoint ID;
- trace and correlation identities.

The signed run specification contains no bearer token, refresh token, plaintext secret, database
credential, NATS credential, provider secret, or plaintext platform secret.

## Attempts and recovery

Runner infrastructure may create another attempt for the same run only when recovery is safe:

- before any externally visible output or non-idempotent action; or
- from a confirmed checkpoint whose subsequent operations are idempotent and deduplicated.

An attempt uses a stable `run_id`, distinct `attempt_id`, monotonically increasing attempt number,
and monotonically increasing `lease_epoch`. The Runner owns the active lease and guarantees at most
one active attempt for a run. Runtime API, State API, LLM Gateway, and MCP Gateway reject operations
from an older epoch, fencing a container that continues after Runner or network failure.

Once visible streaming output has begun, an ambiguous failure does not silently regenerate the
same message. The partial message becomes `interrupted`. A user or policy may start a new run with a
new message ID from the last safe checkpoint.

MCP operations that can cause side effects require caller-supplied idempotency and a tool contract
that defines safe retry. An unknown tool outcome is surfaced as ambiguous and is not automatically
retried.

## Terminal-state ownership

- The Conversation Service owns message and input-request terminal state.
- The Agent Runner owns run and attempt terminal state.
- The State API owns checkpoint commit state.
- A message may complete before its run completes container cleanup.
- A completed message remains completed if later cleanup fails.
- The first valid terminal transition for an entity wins; later conflicting events are retained as
  diagnostics but cannot rewrite product state.
- A run cannot become `completed` until every required final message and checkpoint acknowledgement
  has been accepted.

Completion is an event-driven handshake:

1. Agent sends idempotent `run.result_proposed` through Runtime API.
2. Conversation Service commits required final messages and emits `run.messages_committed`.
3. State API commits any required final checkpoint and emits `run.checkpoint_committed`.
4. Runner waits for the confirmations required by the pinned run contract.
5. Runner transitions the run exactly once and emits `run.completed`, or enters a bounded
   `completion_reconciling` state when a confirmation is missing.

Only Runner owns run terminal state. It never infers success solely from container exit code.

## Cancellation and deadlines

Cancellation is idempotent. The Runner:

1. marks cancellation requested;
2. revokes renewal and new gateway operations;
3. notifies the SDK through the runtime channel;
4. permits a bounded checkpoint/cleanup grace period;
5. terminates the exact container if still alive;
6. publishes one terminal run event.

Deadlines are part of the run specification. SDK calls cannot extend them. User-input suspension
ends the active execution deadline; the later response receives a new run deadline.

## Conversation versioning

A conversation keeps its selected agent release. Publishing, deprecating, or changing a default
does not upgrade it. Changing agent versions requires an explicit new conversation unless a future
versioned migration contract is introduced.
