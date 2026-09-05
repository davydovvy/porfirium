# Porfirium

Porfirium is a multi-user platform for developing and running LangGraph agents in isolated
containers. The target platform separates the user portal, Agent Registry, Agent Runner,
Porfirium Agent SDK, checkpoint service, model/tool gateways, and a NATS JetStream event backbone.
All conversations use agents; the target product has no separate Direct LLM mode.

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

## Target architecture

Each agent is an immutable, digest-pinned OCI release built on LangGraph. The Agent Runner starts
each run attempt in its own constrained container. Agent code uses the Porfirium Agent SDK for user
messages and responses, LLM calls, MCP tools, durable LangGraph checkpoints, cancellation, and
Langfuse telemetry. For MCP calls it receives a short-lived, audience-restricted OIDC token
delegated from the user; the original browser and refresh tokens remain outside the container. It
never receives direct database, NATS, or infrastructure access.

The portal is the only browser-facing boundary. The Agent Registry owns releases and access
grants, the Agent Runner owns isolated execution, and NATS JetStream carries durable commands and
events. Service-owned databases and versioned contracts allow components to evolve independently.

The repository still runs the previous Portal API and Temporal worker. A future implementation
plan will define the transition after the target architecture contracts are accepted.

The authoritative documents are:

- [Architecture](docs/ARCHITECTURE.md) — system boundaries and invariants
- [Specification](SPECIFICATION.md) — target product and engineering contract
- [Runtime model](docs/architecture/RUNTIME_MODEL.md) — conversations, threads, runs, and attempts
- [Service contracts](docs/architecture/SERVICE_CONTRACTS.md) — APIs, ownership, and workflows
- [Messaging and streaming](docs/architecture/MESSAGING.md) — JetStream and token delivery
- [Identity and security](docs/architecture/IDENTITY_AND_SECURITY.md) — delegated OIDC and isolation
- [Agent configuration](docs/architecture/CONFIGURATION.md) — values, revisions, and secret handling
- [Agent SDK](docs/architecture/AGENT_SDK.md) — supported agent-facing interface
- [Planning handoff](docs/architecture/IMPLEMENTATION_HANDOFF.md) — accepted decisions and inputs
- [Operations](docs/OPERATIONS.md) — currently deployed stack procedures
- [Glossary](docs/architecture/GLOSSARY.md) — domain terminology

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
