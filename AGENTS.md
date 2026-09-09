# Repository Guidelines

## Project Structure & Module Organization

Porfirium uses rootless Podman for the target agent platform and Docker Compose for shared gateway
and observability services. Target FastAPI services and their tests live in `services/`. The
React/Vite portal is under `apps/web/src`. Independent MCP servers are also in `services/`, while
immutable versioned agent packages live under `agents/<agent-id>/<version>/`. Deployment
configuration belongs in `compose.yaml` and `deploy/`.
Target architecture, migration, and operator guidance are maintained in `docs/`; repeatable
verification entry points belong in `scripts/`. Avoid accumulating completed-phase narratives in
source docs.

## Build, Test, and Development Commands

- `./scripts/target-phase13/verify.sh` checks the public target portal and production build.
- `./scripts/target-phase12/verify-hardening.sh` runs the target service lint and test suites.
- `./scripts/target-phase12/verify-acceptance.sh` is the complete platform acceptance entry point;
  its recovery and live checks require explicit opt-ins and local credentials.
- `cd apps/web && npm run dev` starts Vite; `npm run lint`, `npm test`, and `npm run build` provide
  focused frontend checks.
- `podman logs porfirium-agent-runtime-api` inspects Runtime failures; use the host Runner process
  logs and `docker compose logs agentgateway` for execution and gateway failures.

## Coding Style & Naming Conventions

Python targets 3.12+, uses four-space indentation, 100-character lines, type annotations, and
Ruff rules `E`, `F`, `I`, `UP`, and `B`. Use `snake_case` for functions/modules and `PascalCase`
for classes. TypeScript uses ESLint, functional React components, `PascalCase.tsx` component
files, and camelCase values. Preserve immutable agent versions; publish a new semantic version
instead of editing an accepted package.

## Testing Guidelines

Backend tests use Pytest/pytest-asyncio and follow `tests/test_*.py`; frontend tests use Vitest and
Testing Library with `*.test.tsx`. Add a regression test for every defect. Run the narrow suite
while developing, then the relevant increment verification script before committing. No numeric
coverage threshold is enforced, but changed authorization, persistence, workflow, and isolation
paths require explicit tests.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects such as `Add filesystem agent publication CLI` or
conventional prefixes such as `feat:` and `docs:`. Keep commits scoped and include migrations,
tests, and documentation with the behavior they change. Pull requests should explain intent and
risk, list commands and actual results, link the relevant plan or issue, and include screenshots
for visible portal changes. Document rollout and rollback for schema or runtime changes.

## Security & Configuration

Never commit `.env`, credentials, tokens, provider payloads, or production data. Keep browser
tokens at the Portal BFF boundary, enforce owner/role checks server-side, and treat prompts, tool
arguments, artifacts, and tool results as untrusted input.
