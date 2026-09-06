from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from configuration_service.domain import canonical_json
from configuration_service.problems import ConfigurationProblem


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    revision_id: UUID
    owner_id: UUID
    release_id: UUID
    scope: str
    conversation_id: UUID | None
    schema_digest: str
    values: dict[str, Any]
    secret_references: dict[str, Any]
    created_at: datetime


def _record(row: asyncpg.Record) -> RevisionRecord:
    return RevisionRecord(**dict(row))


async def get_revision(
    pool: asyncpg.Pool,
    owner_id: UUID,
    revision_id: UUID,
    *,
    connection: asyncpg.Connection | None = None,
) -> RevisionRecord:
    executor = connection or pool
    row = await executor.fetchrow(
        "SELECT * FROM configuration_revisions WHERE revision_id=$1 AND owner_id=$2",
        revision_id,
        owner_id,
    )
    if not row:
        raise ConfigurationProblem(
            404, "revision_not_found", "Configuration revision was not found"
        )
    return _record(row)


async def create_revision(
    pool: asyncpg.Pool,
    *,
    owner_id: UUID,
    release_id: UUID,
    scope: str,
    conversation_id: UUID | None,
    schema_digest: str,
    values: dict[str, Any],
    secret_references: dict[str, Any],
    idempotency_key: str,
) -> RevisionRecord:
    request = [
        str(owner_id),
        str(release_id),
        scope,
        str(conversation_id),
        schema_digest,
        values,
        secret_references,
    ]
    digest = hashlib.sha256(canonical_json(request)).hexdigest()
    async with pool.acquire() as connection, connection.transaction():
        previous = await connection.fetchrow(
            "SELECT request_sha256,revision_id FROM configuration_idempotency "
            "WHERE owner_id=$1 AND idempotency_key=$2 FOR UPDATE",
            owner_id,
            idempotency_key,
        )
        if previous:
            if previous["request_sha256"] != digest:
                raise ConfigurationProblem(
                    409, "idempotency_conflict", "Idempotency key was reused"
                )
            return await get_revision(
                pool, owner_id, previous["revision_id"], connection=connection
            )
        revision_id = uuid4()
        row = await connection.fetchrow(
            "INSERT INTO configuration_revisions "
            "(revision_id,owner_id,release_id,scope,conversation_id,schema_digest,"
            "values,secret_references) "
            "VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) RETURNING *",
            revision_id,
            owner_id,
            release_id,
            scope,
            conversation_id,
            schema_digest,
            canonical_json(values).decode(),
            canonical_json(secret_references).decode(),
        )
        await connection.execute(
            "INSERT INTO configuration_idempotency"
            "(owner_id,idempotency_key,request_sha256,revision_id) "
            "VALUES($1,$2,$3,$4)",
            owner_id,
            idempotency_key,
            digest,
            revision_id,
        )
        return _record(row)
