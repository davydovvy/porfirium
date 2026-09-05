# Architecture glossary

## Conversation

A user-owned interaction history associated with one selected agent release. The portal maintains
a read projection from durable conversation and run events.

## Thread

The LangGraph checkpoint namespace associated with a conversation. A thread survives individual
runs and containers and can resume from an acknowledged checkpoint.

## Run

One bounded LangGraph activation caused by a user message, user response, or explicit resume. A run
has one pinned specification and exactly one terminal outcome, but may have more than one safe
recovery attempt.

## Attempt

One isolated container execution for a run. At most one attempt is active for a run. Containers are
never reused across attempts, runs, users, or releases.

## Agent

A stable registry identity that groups independently published versions and access grants. An
agent identity does not contain executable behavior.

## Agent release

An immutable semantic version that binds metadata, a digest-pinned OCI image, SDK compatibility,
configuration schema, requested capabilities, and provenance. Deprecation blocks new selection but
does not modify prior runs.

## Agent manifest

The validated declaration shipped with an agent release. It identifies the LangGraph entrypoint,
OCI digest, SDK range, requested models/tools, configuration schema, and resource requirements.

## Run specification

A signed immutable contract resolved by the Agent Registry after authorization. It pins the
release, image digest, effective configuration, model/tool grants, resource limits, SDK protocol,
user, and trace identity used by one run. It contains no bearer token.

## Run capability

A short-lived, revocable credential issued for one run. It authorizes only the SDK operations and
resources listed in the run specification and cannot be reused by another run.

## Delegated user token

A short-lived OIDC access token created by exchanging the portal-held user token. It represents the
user, is restricted to the MCP Gateway audience and approved scopes, and is provided to one active
agent run for user-authorized tool calls. It is not the browser token and is never refreshable by
agent code directly.

## Delegation grant

A durable, revocable, non-secret reference connecting a server-side user session authorization to
an allowed conversation, release, and maximum MCP scopes. Only its opaque ID crosses asynchronous
admission boundaries; possession of the ID alone cannot mint a token.

## Configuration revision

An immutable version of user or conversation configuration validated against the release schema.
Runs pin the effective revision and schema digest so later edits cannot change accepted work.

## Checkpoint

A versioned LangGraph state snapshot stored through the SDK and State API. It supports recovery and
human-input suspension but is separate from portal chat history and JetStream message retention.

## Input request

A durable request for user data correlated with a committed checkpoint. Creating it suspends the
thread and ends the active container. One effective response starts a new run from that checkpoint.

## Suspension

An idempotent saga that commits a checkpoint and correlated input request under one stable
`suspension_id`. The thread is resumable only after both records are confirmed.

## Lease epoch

A monotonically increasing fencing number for attempts of one run. SDK-facing services reject an
older epoch so a stale container cannot continue acting after recovery starts another attempt.

## Message delta

A bounded, ordered fragment of a streaming message. Deltas have short retention and support live
display and reconnect; the validated canonical completion is the durable message record.

## Command

A durable request for an owning component to attempt an action, such as starting or cancelling a
run. Commands are idempotent and may be delivered more than once.

## Event

An immutable fact about something that already happened. Events use versioned schemas, stable IDs,
per-aggregate sequence numbers, correlation and causation IDs, and trace context.

## Tool grant

An explicit authorization for a pinned agent run to invoke one reviewed MCP tool under bounded
policy. Tool discovery alone never grants execution permission.
