# Agent configuration contract

Status: accepted architecture contract

## Ownership

- Agent Registry owns the configuration JSON Schema, non-secret release defaults, and which fields
  are mutable per user or conversation.
- Configuration Service owns versioned user and conversation configuration values plus opaque
  secret references.
- Conversation Service owns the configuration revision selected by a conversation.
- Runner pins the validated effective configuration revision in the run specification.
- The SDK exposes only the effective non-secret configuration intended for agent code.

Configuration precedence is deterministic:

```text
release defaults <- user values <- conversation values
```

Each layer may override only fields permitted by the release schema. Unknown fields, invalid types,
or attempts to exceed platform limits fail before run admission.

## Immutability

Configuration updates create a new revision. Existing runs retain their pinned revision. Existing
conversations do not silently adopt new values; the user must explicitly select a newer compatible
revision for future runs.

The run specification contains canonical non-secret values, configuration revision IDs, schema
digest, and versioned secret references. It never contains plaintext secrets.

## Delivery

Runner delivers bounded non-secret configuration as a read-only file or Runtime API bootstrap frame.
SDK validates its schema/digest and exposes typed access. Configuration is not copied into generic
environment variables, command-line arguments, logs, events, checkpoints, or telemetry.

The initial platform does not expose arbitrary secret values to agent code. Platform service
credentials remain at their owning gateway. User authorization for MCP is delivered through the
separate delegated-token contract. A future agent-specific external-secret capability requires a
new brokered, destination-scoped architecture decision.

## Access and audit

Users may read and update only their configuration and conversations. Agent publishers define
schemas/defaults but cannot read user values. Every revision change and selection is audited with
user, release, schema digest, revision, and correlation identity without recording secret values.

Deletion or revocation of a configuration revision blocks future admission but does not rewrite
retained run specifications. Secret revocation takes effect immediately at the owning service.
