import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://genai:genai@application-postgres:5432/genai"
    )
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "https://keycloak.local:8443/realms/GenAI-platform")
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "genai-demo-api")
    oidc_required_role: str = os.getenv("OIDC_REQUIRED_ROLE", "genai-user")
    oidc_ca_file: str | None = os.getenv("OIDC_CA_FILE")
    oidc_jwks_url: str | None = os.getenv("OIDC_JWKS_URL")
    model_gateway_provider: str = os.getenv("MODEL_GATEWAY_PROVIDER", "bifrost")
    model_gateway_url: str = os.getenv(
        "MODEL_GATEWAY_URL", os.getenv("BIFROST_URL", "http://bifrost:8080")
    )
    tool_gateway_provider: str = os.getenv("TOOL_GATEWAY_PROVIDER", "bifrost")
    tool_gateway_url: str = os.getenv(
        "TOOL_GATEWAY_URL", os.getenv("BIFROST_URL", "http://bifrost:8080")
    )
    tool_gateway_timeout_seconds: float = float(
        os.getenv("TOOL_GATEWAY_TIMEOUT_SECONDS", "20")
    )
    bifrost_model_prefix: str = os.getenv("BIFROST_MODEL_PREFIX", "yandex/")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    llm_max_output_tokens: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2048"))
    temporal_address: str = os.getenv("TEMPORAL_ADDRESS", "temporal:7233")
    temporal_namespace: str = os.getenv("TEMPORAL_NAMESPACE", "default")
    temporal_task_queue: str = os.getenv("TEMPORAL_TASK_QUEUE", "porfirium-agent-v1")

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"


settings = Settings()
