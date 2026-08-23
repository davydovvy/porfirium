FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY portal_api portal_api
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY migrations migrations
USER 65532:65532
EXPOSE 8000
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && exec .venv/bin/uvicorn portal_api.main:app --host 0.0.0.0 --port 8000"]
