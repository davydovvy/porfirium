# Porfirium

Porfirium is a local-first agent and LLM demonstration platform. The repository contains the completed Phases 0–2 plus the user-testable Phase 3 durable Agent increment.

## Phase 3 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase3/start.sh
./scripts/phase3/verify.sh
```

Open `https://portal.local:8444`, use the Direct/Agent selector to filter conversations, select `Agent`, and create a conversation. Temporal is available at `http://localhost:8080`; Bifrost and Langfuse remain available at their Phase 2 URLs. See [the Phase 3 runbook](docs/phase3/RUNBOOK.md) for operation, worker-restart recovery, and inspection commands.

## Phase 2 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase2/start.sh
./scripts/phase2/verify.sh
```

Open `https://portal.local:8444`, sign in, and create a persistent conversation. Bifrost is available at `http://localhost:8088` and Langfuse at `http://localhost:3000`. See [the Phase 2 runbook](docs/phase2/RUNBOOK.md) for operation and recovery details.

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

Phase evidence is recorded in [Phase 0 results](docs/phase0/RESULTS.md), [Phase 1 results](docs/phase1/RESULTS.md), [Phase 2 results](docs/phase2/RESULTS.md), and [Phase 3 results](docs/phase3/RESULTS.md). Phases 0–3 are implemented and accepted; Phase 4 has not started.
