FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

WORKDIR /sdk
COPY packages/agent-sdk-python/pyproject.toml ./
COPY packages/agent-sdk-python/porfirium_agent_sdk porfirium_agent_sdk
RUN uv pip install --system .

COPY scripts/target-phase5/harness.py /harness.py
USER 65532:65532
CMD ["python", "/harness.py"]
