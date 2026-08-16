# Porfirium

Porfirium is a local-first agent and LLM demonstration platform. The repository contains the completed Phase 0 diagnostics increment and the user-testable Phase 1 authenticated platform skeleton.

## Phase 1 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase1/start.sh
./scripts/phase1/verify.sh
```

Open `https://portal.local:8444`. Sign in as `alise` or `bob`; both local demo passwords are `123456`. See [the Phase 1 runbook](docs/phase1/RUNBOOK.md) for the one-time local CA trust step, recovery commands, and scope boundaries.

## Phase 0 quick start

Prerequisites:

- Linux, Docker Engine, and Docker Compose;
- standalone Keycloak already running from `/home/dvy/Projects/KeyCloak`;
- Yandex configuration present in this project's uncommitted `.env`.

Run:

```bash
./scripts/phase0/start.sh
./scripts/phase0/verify.sh
```

Inspect:

- Bifrost: <http://localhost:8088>
- Langfuse: <http://localhost:3000>
- diagnostic MCP health: <http://localhost:8091/health>
- Keycloak: <https://keycloak.local:8443>

The generated Langfuse login password is stored in the uncommitted `.env` file under `LANGFUSE_INIT_USER_PASSWORD`. Do not paste or commit it.

Status and resource usage:

```bash
./scripts/phase0/status.sh
./scripts/phase0/licenses.sh
```

Stop without deleting persistent state:

```bash
./scripts/phase0/stop.sh
```

See [the Phase 0 runbook](docs/phase0/RUNBOOK.md) for verification and recovery details. Product architecture and later phases are defined in [SPECIFICATION.md](SPECIFICATION.md).

Phase 0 evidence is recorded in [Phase 0 results](docs/phase0/RESULTS.md). Current identity/portal evidence and limitations are recorded in [Phase 1 results](docs/phase1/RESULTS.md). Phase 1 is implemented and awaiting user handoff review.
