# Agent Runner

The Runner owns idempotent run admission, attempt leases, rootless Podman containers, cancellation,
deadlines, and reconciliation. Callers provide only run identity and an immutable release selection;
the Registry resolves and signs the complete run specification and the Runner derives all container
settings.

Apply migrations before starting the service:

```bash
uv run python -m agent_runner.migrate
uv run uvicorn agent_runner.main:app --host 0.0.0.0 --port 8103
```

Required configuration is `DATABASE_URL`, the NATS variables used by readiness,
`AGENT_REGISTRY_URL`, `AGENT_RUNTIME_URL`, `REGISTRY_RESOLVER_TOKEN`,
`REGISTRY_RUN_PUBLIC_KEYS` (a JSON object mapping key IDs to base64 Ed25519 public keys), and
`RUN_CAPABILITY_SECRET` shared with Runtime API.

The service process must run as an unprivileged user with access to rootless Podman. Agent containers
receive a numeric non-root identity, read-only root, bounded noexec tmpfs, no capabilities, no new
privileges, no network, bounded CPU/memory/PIDs/file descriptors, and no host mounts or runtime
socket. Cancellation always uses the container ID persisted for the active attempt.

Run focused checks with:

```bash
uv run ruff check .
uv run pytest -q
../../scripts/feasibility/rootless-container-isolation/verify.sh
```
