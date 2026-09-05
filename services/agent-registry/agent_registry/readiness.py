from __future__ import annotations

import os

import asyncpg
import httpx
import nats
from fastapi import HTTPException, status
from nats.aio.client import Client as NatsClient
from nats.errors import Error as NatsError


async def check_database() -> None:
    connection = await asyncpg.connect(os.environ["DATABASE_URL"], timeout=2)
    try:
        await connection.fetchval("SELECT 1")
    finally:
        await connection.close()


async def check_nats() -> None:
    client: NatsClient = await nats.connect(
        os.environ["NATS_URL"],
        user=os.environ["NATS_USER"],
        password=os.environ["NATS_PASSWORD"],
        connect_timeout=2,
        max_reconnect_attempts=0,
    )
    try:
        await client.flush(timeout=2)
    finally:
        await client.close()


async def check_registry() -> None:
    async with httpx.AsyncClient(timeout=2) as client:
        response = await client.get(f"{os.environ['OCI_REGISTRY_URL']}/v2/")
        response.raise_for_status()


async def check_dependencies() -> None:
    try:
        await check_database()
        await check_nats()
        await check_registry()
    except (
        KeyError,
        OSError,
        TimeoutError,
        asyncpg.PostgresError,
        httpx.HTTPError,
        NatsError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dependency unavailable",
        ) from None
