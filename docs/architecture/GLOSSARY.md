# Architecture glossary

This glossary defines Porfirium-specific usage where an industry term can have more than one meaning.

## Conversation

A user-owned sequence of messages in either Direct or Agent mode. An Agent conversation records the published agent version selected when the conversation is created.

## Turn

One user submission and the platform's complete attempt to respond to it. A turn begins when the API accepts the submission and ends as `completed`, `failed`, or `cancelled`. It owns the execution state, ordered events, correlation ID, optional Temporal workflow ID, tool audit records, and—for Agent mode—the pinned run snapshot.

Dialogue literature sometimes calls each individual speaker utterance a turn. Porfirium instead uses *turn* for the request's complete execution lifecycle; the individual user and assistant utterances are stored as messages.

## Agent

A stable catalog identity such as `tool-assistant`. It groups independently published versions but does not itself define mutable runtime behavior.

## Agent version

An immutable published release such as `tool-assistant:1.0.0`. It binds a validated manifest and canonical digest to a model alias and explicit tool grants. Deprecation may prevent future selection but does not mutate or delete historical release content.

## Manifest

The validated JSON description of an agent version: identity, runtime type, workflow contract, model alias, instructions, requested tools, and execution limits. A manifest requests capabilities; platform policy and catalog grants authorize them.

## Digest

A `sha256:` identifier calculated from the canonical JSON representation of a manifest. It detects any change to the release definition and is stored with publications and run snapshots.

## Pinned run snapshot

An immutable copy of the resolved execution contract created when an Agent turn is accepted. It contains the exact agent-version ID and digest, manifest, resolved model information, and granted tool identities used by that turn.

Pinning prevents later default changes, new publications, grant changes, or worker restarts from silently changing an accepted turn. Historical and long-running Temporal executions can therefore be audited against the configuration with which they began.

## Tool grant

An explicit association between one published agent version and one stable tool-catalog entry. Tool discovery alone does not grant execution permission, and the application still validates identity, arguments, schema, and policy on every call.
