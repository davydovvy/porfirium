from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentIdentity, Identity
from .config import settings
from .db import get_session
from .models import User

app = FastAPI(title="Porfirium Portal API", version="0.1.0")
Session = Annotated[AsyncSession, Depends(get_session)]


async def ensure_user(identity: Identity, session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.keycloak_subject == identity.subject))
    if user is None:
        user = User(keycloak_subject=identity.subject)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(session: Session) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready"}


@app.get("/api/v1/config")
async def config() -> dict[str, str]:
    return {
        "oidc_issuer": settings.oidc_issuer,
        "oidc_client_id": "genai-demo-web",
        "api_audience": settings.oidc_audience,
    }


@app.get("/api/v1/me")
async def me(identity: CurrentIdentity, session: Session) -> dict[str, object]:
    user = await ensure_user(identity, session)
    return {
        "id": str(user.id),
        "username": identity.username,
        "display_name": identity.display_name,
        "email": identity.email,
        "roles": identity.roles,
        "capabilities": {"chat": True, "agent": False, "tools": False},
    }


@app.get("/api/v1/conversations")
async def conversations(identity: CurrentIdentity, session: Session) -> list[object]:
    user = await ensure_user(identity, session)
    # Phase 1 deliberately exposes an empty shell; Phase 2 adds conversation operations.
    return [] if user else []
