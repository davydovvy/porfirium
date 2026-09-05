FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY agent_runner agent_runner
COPY migrations migrations
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 65532:65532
EXPOSE 8103
CMD ["uvicorn", "agent_runner.main:app", "--host", "0.0.0.0", "--port", "8103"]
