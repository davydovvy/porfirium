import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://genai:genai@application-postgres:5432/genai"
    )
    oidc_issuer: str = os.getenv(
        "OIDC_ISSUER", "https://keycloak.local:8443/realms/GenAI-platform"
    )
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "genai-demo-api")
    oidc_required_role: str = os.getenv("OIDC_REQUIRED_ROLE", "genai-user")
    oidc_ca_file: str | None = os.getenv("OIDC_CA_FILE")
    oidc_jwks_url: str | None = os.getenv("OIDC_JWKS_URL")

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"


settings = Settings()
