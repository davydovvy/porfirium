from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from identity_delegation.problems import DelegationProblem


@dataclass(frozen=True, slots=True)
class GrantRecord:
    grant_id: UUID
    user_id: UUID
    conversation_id: UUID
    release_id: UUID
    maximum_scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


def record(row: asyncpg.Record) -> GrantRecord:
    return GrantRecord(**dict(row))


async def create_grant(
    pool: asyncpg.Pool,
    *,
    user_id: UUID,
    conversation_id: UUID,
    release_id: UUID,
    maximum_scopes: list[str],
    expires_at: datetime,
    idempotency_key: str,
) -> GrantRecord:
    digest = hashlib.sha256(
        json.dumps(
            [
                str(user_id),
                str(conversation_id),
                str(release_id),
                sorted(maximum_scopes),
                expires_at.isoformat(),
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    async with pool.acquire() as connection, connection.transaction():
        previous = await connection.fetchrow(
            "SELECT request_sha256,grant_id FROM delegation_idempotency "
            "WHERE actor_id=$1 AND operation='create' AND idempotency_key=$2 FOR UPDATE",
            user_id,
            idempotency_key,
        )
        if previous:
            if previous["request_sha256"] != digest:
                raise DelegationProblem(409, "idempotency_conflict", "Idempotency key was reused")
            return await get_grant(pool, previous["grant_id"], connection=connection)
        grant_id = uuid4()
        row = await connection.fetchrow(
            "INSERT INTO delegation_grants"
            "(grant_id,user_id,conversation_id,release_id,maximum_scopes,expires_at) "
            "VALUES($1,$2,$3,$4,$5,$6) RETURNING *",
            grant_id,
            user_id,
            conversation_id,
            release_id,
            sorted(set(maximum_scopes)),
            expires_at,
        )
        await connection.execute(
            "INSERT INTO delegation_idempotency"
            "(actor_id,operation,idempotency_key,request_sha256,grant_id) "
            "VALUES($1,'create',$2,$3,$4)",
            user_id,
            idempotency_key,
            digest,
            grant_id,
        )
        return record(row)


async def get_grant(
    pool: asyncpg.Pool, grant_id: UUID, *, connection: asyncpg.Connection | None = None
) -> GrantRecord:
    row = await (connection or pool).fetchrow(
        "SELECT * FROM delegation_grants WHERE grant_id=$1", grant_id
    )
    if not row:
        raise DelegationProblem(404, "grant_not_found", "Delegation grant was not found")
    return record(row)


async def revoke_grant(pool: asyncpg.Pool, grant_id: UUID) -> None:
    result = await pool.execute(
        "UPDATE delegation_grants SET revoked_at=coalesce(revoked_at,now()) WHERE grant_id=$1",
        grant_id,
    )
    if result == "UPDATE 0":
        raise DelegationProblem(404, "grant_not_found", "Delegation grant was not found")
