# Porfirium

Porfirium is a local-first platform for building and running durable LLM agents. It provides a
React portal, a FastAPI control plane, Temporal orchestration, Agentgateway-backed model and MCP
access, immutable versioned agent releases, and self-hosted observability.

## Start and verify

Prerequisites are Linux, Docker Engine with Compose, the standalone Keycloak project, a
`portal.local` mapping to `127.0.0.1`, and an uncommitted `.env` containing local secrets and
Yandex settings.

```bash
./scripts/phase4/start.sh
./scripts/phase4/verify.sh
```

Open <https://portal.local:8444>. Supporting interfaces are available at:

- Temporal: <http://localhost:8080>
- Agentgateway: <http://localhost:8089>
- Langfuse: <http://localhost:3000>
- Keycloak: <https://keycloak.local:8443>

See [Operations](docs/OPERATIONS.md) for startup, authoring, publication, recovery, and rollback.

## Current architecture

Agentgateway is the sole model and MCP gateway. Direct conversations call it through the Portal
API. Agent conversations are accepted against an immutable agent release and a self-contained run
snapshot, then executed by the platform-owned `AgentRunWorkflow` on Temporal queue
`porfirium-agent-runtime-v1`. Application code remains authoritative for identity, ownership,
tool policy, persistence, and audit.

Declarative agents can be published from version directories or authored in the portal. Published
versions, grants, artifacts, and accepted run snapshots are immutable. Publication never silently
changes a default, and existing conversations never follow a newer release.

The authoritative documents are:

- [Architecture](docs/ARCHITECTURE.md) — system boundaries and invariants
- [Specification](SPECIFICATION.md) — current product and engineering contract
- [Operations](docs/OPERATIONS.md) — supported operator workflows
- [Glossary](docs/architecture/GLOSSARY.md) — domain terminology
- [Executable-agent isolation proposal](docs/architecture/INCREMENT10_PLAN.md) — unimplemented
  design

## Development

Focused commands:

```bash
cd apps/portal-api
uv run pytest -q
uv run ruff check .

cd ../web
npm run lint
npm test -- --run
npm run build
```

See [Repository Guidelines](AGENTS.md) for repository layout, conventions, and security guidance.
