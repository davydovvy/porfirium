# LangGraph HTTP State API gate

Status: **accepted on LangGraph 1.2.11 / langgraph-checkpoint 4.2.0**

This gate compiles a LangGraph workflow with a custom `BaseCheckpointSaver` that communicates only
with an HTTP State API. The State API owns its SQLite persistence file and stores checkpoint,
metadata, and pending-write values serialized by LangGraph's `JsonPlusSerializer` in strict
MessagePack mode.

The verifier starts the State API, runs one agent process until `interrupt()`, terminates and
restarts the State API, then launches a second agent process with `Command(resume=...)`. It rejects
agent-side database imports or configuration and requires multiple durable checkpoints.

```bash
./scripts/feasibility/langgraph-state-api/verify.sh
```

Dependencies are installed into `/tmp/porfirium-langgraph-state-api-venv` from
`requirements.lock`; override the location with `PORFIRIUM_LANGGRAPH_GATE_VENV`.

## Accepted observation

On 2026-09-05 the verifier persisted three serialized checkpoints through HTTP. The first agent
process stopped at a stable approval interrupt, the State API process was terminated and restarted
against its durable store, and a new agent process resumed the thread with `Command(resume="yes")`.
It produced `approved:yes` without receiving a database path or importing a database driver.

Decision: implement the SDK checkpointer as an HTTP adapter to the platform-owned State API. Use
strict MessagePack deserialization with a bounded type allowlist, preserve pending writes, and keep
database ownership and credentials exclusively in the State API.
