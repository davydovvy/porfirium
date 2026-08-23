# Porfirium

Porfirium is a local-first agent and LLM demonstration platform. Phases 0–4 are implemented and accepted; Phase 4 adds policy-controlled MCP tools to the durable Agent.

## Architecture transition

The active architecture transition has moved both gateway roles from Bifrost to Agentgateway and now introduces independently developed, immutable agent packages that can be published from the filesystem or authored declaratively in the portal. The staged plan, compatibility gates, target component boundaries, versioning model, and rollback rules are documented in [Agentgateway and Versioned Agent Platform Transition Plan](docs/architecture/AGENTGATEWAY_AGENT_PLATFORM_TRANSITION.md).

Transition Increments 0–9 and Milestones M1–M4 are complete and accepted. Agentgateway 1.4.0 is the sole model and MCP provider through `AgentgatewayModelGateway` and `AgentgatewayToolGateway`; Bifrost has been removed from runtime, configuration, and current verification paths. Every accepted Agent turn is pinned to an immutable version and self-contained run snapshot. Rerun the current gates with `./scripts/phase4/verify.sh`, `./scripts/increment8/verify.sh`, and `./scripts/increment9/verify.sh`. Cumulative evidence is tracked in [Architecture Transition Results](docs/architecture/TRANSITION_RESULTS.md).

Increment 7 is accepted. The platform-owned `AgentRunWorkflow` executes immutable declarative run snapshots on the sole `porfirium-agent-runtime-v1` queue; the bundled `tool-assistant:1.2.0` release is the default generic release with a corrected versioned MTG set-search contract, while `1.0.0` and `1.1.0` remain immutable historical data. See the [Increment 7 plan](docs/architecture/INCREMENT7_PLAN.md) and [acceptance results](docs/architecture/INCREMENT7_RESULTS.md).

Increment 8 is accepted. It adds independent declarative publication from version directories. The filesystem-published `tool-assistant:1.3.0` release is available for explicit selection; publication does not change the default or existing conversations. See the [Increment 8 results](docs/architecture/INCREMENT8_RESULTS.md) and [filesystem publication runbook](docs/architecture/INCREMENT8_RUNBOOK.md).

Increment 9 and Milestone M4 are accepted. Separately authorized users can create, revise,
validate, privately test, publish, and deprecate declarative agents through the portal while
reusing the immutable publication and generic runtime contracts. See the
[Increment 9 results](docs/architecture/INCREMENT9_RESULTS.md) and
[portal builder runbook](docs/architecture/INCREMENT9_RUNBOOK.md).

The quick starts and phase documents below retain the accepted Phase 0–4 behavior while current model and Agent tool traffic use Agentgateway.

## Current runtime and filesystem publication

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase4/start.sh
./scripts/phase4/verify.sh
```

Open `https://portal.local:8444`. Direct and Agent modes are available. Agent conversations use the selected immutable declarative release and the generic Temporal worker; inspect it with `docker compose logs agent-worker` and the Temporal UI at `http://localhost:8080`. See [the Phase 4 runbook](docs/phase4/RUNBOOK.md) for operation, verification, recovery, and rollback, and the [architecture glossary](docs/architecture/GLOSSARY.md) for platform terminology.

Validate the Increment 8 canary offline, then inspect its live publication:

```bash
cd apps/portal-api
.venv/bin/porfirium agents validate ../../agents/tool-assistant/1.3.0 --json
cd ../..
docker compose exec portal-api .venv/bin/porfirium agents status tool-assistant:1.3.0 --json
```

Use the Increment 8 runbook before publishing another version.

## Phase 3 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase3/start.sh
./scripts/phase3/verify.sh
```

Open `https://portal.local:8444`, use the Direct/Agent selector to filter conversations, select `Agent`, and create a conversation. Temporal is available at `http://localhost:8080`; Agentgateway is at `http://localhost:8089` and Langfuse at `http://localhost:3000`. See [the Phase 3 runbook](docs/phase3/RUNBOOK.md) for operation, worker-restart recovery, and inspection commands.

## Phase 2 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase2/start.sh
./scripts/phase2/verify.sh
```

Open `https://portal.local:8444`, sign in, and create a persistent conversation. Agentgateway is available at `http://localhost:8089` and Langfuse at `http://localhost:3000`. See [the Phase 2 runbook](docs/phase2/RUNBOOK.md) for operation and recovery details.

## Phase 1 quick start

With the standalone Keycloak prerequisite running and `portal.local` mapped to `127.0.0.1`:

```bash
./scripts/phase1/start.sh
./scripts/phase1/verify.sh
```

Open `https://portal.local:8444`. Sign in as `alise` or `bob`; both local demo passwords are `123456`. See [the Phase 1 runbook](docs/phase1/RUNBOOK.md) for the one-time local CA trust step, recovery commands, and scope boundaries.

## Historical Phase 0 baseline

Prerequisites:

- Linux, Docker Engine, and Docker Compose;
- standalone Keycloak already running from `/home/dvy/Projects/KeyCloak`;
- Yandex configuration present in this project's uncommitted `.env`.

Phase 0 documents preserve the original Bifrost-era connectivity baseline and acceptance evidence. Its retired smoke path is no longer runnable against the current topology. Use the Phase 4 or migration verification commands above for current operation. Product architecture and later phases are defined in [SPECIFICATION.md](SPECIFICATION.md).

Phase evidence is recorded in [Phase 0 results](docs/phase0/RESULTS.md), [Phase 1 results](docs/phase1/RESULTS.md), [Phase 2 results](docs/phase2/RESULTS.md), [Phase 3 results](docs/phase3/RESULTS.md), and [Phase 4 results](docs/phase4/RESULTS.md). Phases 0–4 are implemented and accepted.

## Contributing

See [Repository Guidelines](AGENTS.md) for repository layout, development commands, coding and
testing conventions, pull-request expectations, and security guidance.
