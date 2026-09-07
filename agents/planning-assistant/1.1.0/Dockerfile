FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim@sha256:531f855bda2c73cd6ef67d56b733b357cea384185b3022bd09f05e002cd144ca

COPY packages/agent-sdk-python /opt/porfirium-agent-sdk
RUN uv pip install --system --no-cache /opt/porfirium-agent-sdk

WORKDIR /agent
COPY agents/planning-assistant/1.1.0/planning_assistant.py ./

USER 65532:65532
ENTRYPOINT ["python", "-m", "planning_assistant"]
