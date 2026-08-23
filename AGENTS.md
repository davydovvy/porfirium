# Repository Guidelines

## Project Structure & Module Organization

Porfirium is a Docker Compose–based agent platform. The FastAPI control plane and Temporal worker
live in `apps/portal-api/portal_api`; backend tests are in `apps/portal-api/tests`, and Alembic
migrations are in `apps/portal-api/migrations`. The React/Vite portal is under `apps/web/src`.
Independent MCP servers are in `services/`, while immutable versioned agent packages live under
`agents/<agent-id>/<version>/`. Deployment configuration belongs in `compose.yaml` and `deploy/`.
Architecture decisions, runbooks, and acceptance evidence are maintained in `docs/`; repeatable
operator and verification entry points belong in `scripts/`.

## Build, Test, and Development Commands

- `./scripts/phase4/start.sh` starts the current local stack (standalone Keycloak is required).
- `./scripts/phase4/verify.sh` runs the accepted platform-wide verification suite.
- `./scripts/increment9/verify.sh` checks portal authoring, backend, frontend, and production build.
- `cd apps/portal-api && uv run pytest -q` runs backend tests; `uv run ruff check .` lints Python.
- `cd apps/web && npm run dev` starts Vite; `npm run lint`, `npm test`, and `npm run build` provide
  focused frontend checks.
- `docker compose logs portal-api agent-worker` inspects API and durable-runtime failures.

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
tokens at the Portal API boundary, enforce owner/role checks server-side, and treat prompts, tool
arguments, artifacts, and tool results as untrusted input.
