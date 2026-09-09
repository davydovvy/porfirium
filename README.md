# Porfirium

Porfirium is a multi-user platform for developing and running LangGraph agents in isolated
containers. The target platform separates the user portal, Agent Registry, Agent Runner,
Porfirium Agent SDK, checkpoint service, model/tool gateways, and a NATS JetStream event backbone.
All conversations use agents; the target product has no separate Direct LLM mode.

## Start and verify

Prerequisites are Linux, rootless Podman with Compose, Docker Engine for the shared gateways and
observability services, the standalone Keycloak project, a `portal.local` mapping to `127.0.0.1`,
and the ignored local target environment files described in the operations guide.

```bash
./scripts/target-phase13/verify.sh
```

Open <https://portal.local:8444>. Supporting interfaces are available at:

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

The target implementation has completed Phases 0–12: contracts and feasibility, service
infrastructure, Registry, Checkpoint API and SDK, Runtime API and message SDK, isolated Runner,
configuration and delegation, durable conversations, end-to-end run completion, container-free
human-input suspension, the Portal BFF/web migration, and final hardening. That hardening adds
bounded consumer failure handling, dead-letter inspection and replay, capacity enforcement,
orphan cleanup, an adjacent-minor Runtime compatibility window, trusted-builder provenance policy,
bounded retention,
backup/restore tooling, signed end-to-end trace propagation, and malformed-event containment. A
second immutable target package now provides a two-stage planning assistant with its own signed
publication workflow. The additive Runtime protocol and Python SDK now define bounded typed tool
calls and propagate signed per-run tool grants. Runtime exchanges the opaque delegation grant on
each call, retains the short-lived user token only in memory, and forwards both authorization
dimensions to the MCP boundary. Phase 13 has moved the target portal to the public
`https://portal.local:8444` origin; only browser confirmation and legacy retirement remain.

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
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md) — active sequence, gates, and cutover strategy
- [Operations](docs/OPERATIONS.md) — currently deployed stack procedures
- [Glossary](docs/architecture/GLOSSARY.md) — domain terminology

Target service interfaces are maintained separately from service implementations in
[`packages/contracts`](packages/contracts). They currently establish Registry, Runner,
Conversation, Checkpoint, Configuration, and Identity Delegation HTTP boundaries, durable message
events, common HTTP errors, and the SDK/Runtime stream.

## Development

Focused commands:

```bash
./scripts/contracts/verify.sh
./scripts/target-phase2/acceptance.sh
./scripts/target-phase3/acceptance.sh
./scripts/target-phase4/acceptance.sh
./scripts/target-phase5/acceptance.sh
./scripts/target-phase7/verify.sh
./scripts/target-phase8/verify.sh
./scripts/target-phase9/verify.sh
./scripts/target-phase10/verify.sh
./scripts/target-phase11/verify.sh
./scripts/target-phase12/verify-hardening.sh
./scripts/target-phase12/verify-agents.sh
./scripts/target-phase12/verify-lifecycle.sh
# Requires the supported rootless Podman host.
./scripts/target-phase12/verify-network-isolation.sh
# Requires a running target topology and test credentials.
./scripts/target-phase12/acceptance.sh
# Final gate; requires explicit recovery and live opt-ins.
PHASE12_INCLUDE_RECOVERY=true PHASE12_INCLUDE_LIVE=true \
  ./scripts/target-phase12/verify-acceptance.sh
./scripts/target-runner/verify.sh
./scripts/target-model-only/verify.sh
python3 scripts/target-keycloak/configure.py

cd apps/portal-api
uv run pytest -q
uv run ruff check .

cd ../web
npm run lint
npm test -- --run
npm run build
```

See [Repository Guidelines](AGENTS.md) for repository layout, conventions, and security guidance.
