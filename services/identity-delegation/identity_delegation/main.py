from typing import Literal, TypedDict

from fastapi import Depends, FastAPI

from identity_delegation.readiness import check_dependencies

SERVICE_NAME = "identity-delegation"
SERVICE_VERSION = "0.1.0"


class HealthResponse(TypedDict):
    status: Literal["ok"]
    service: str
    version: str


app = FastAPI(title="Identity Delegation", version=SERVICE_VERSION)


def health_response() -> HealthResponse:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return health_response()


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    dependencies=[Depends(check_dependencies)],
)
async def ready() -> HealthResponse:
    return health_response()
