from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from agent_registry.auth import ServiceIdentity
from agent_registry.domain import AGENT_ID_PATTERN, request_sha256
from agent_registry.publication import Pool, PublishedRelease, _from_row

SubjectType = Literal["user", "group", "role"]
Permission = Literal["discover", "run", "publish", "admin"]


class AccessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AccessGrant:
    grant_id: UUID
    agent_id: str
    subject_type: str
    subject_id: str
    permission: str
    revoked: bool = False

    def contract_response(self) -> dict[str, object]:
        return {
            "grant_id": str(self.grant_id),
            "agent_id": self.agent_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "permission": self.permission,
            "revoked": self.revoked,
        }


def _subjects(identity: ServiceIdentity) -> tuple[str, list[str], list[str]]:
    return identity.subject, sorted(identity.groups), sorted(identity.roles)


async def list_visible_agents(pool: Pool, identity: ServiceIdentity) -> list[dict[str, object]]:
    user_id, groups, roles = _subjects(identity)
    rows = await pool.fetch(
        """
        SELECT a.agent_id, a.name, a.description, a.default_release_id
        FROM agents AS a
        WHERE EXISTS (
            SELECT 1 FROM access_grants AS g
            WHERE g.agent_id = a.agent_id AND g.revoked_at IS NULL
              AND g.permission IN ('discover', 'run', 'admin')
              AND ((g.subject_type = 'user' AND g.subject_id = $1)
                OR (g.subject_type = 'group' AND g.subject_id = ANY($2::text[]))
                OR (g.subject_type = 'role' AND g.subject_id = ANY($3::text[])))
        ) AND EXISTS (
            SELECT 1 FROM releases AS r
            WHERE r.agent_id = a.agent_id AND r.status = 'published'
        )
        ORDER BY a.name, a.agent_id
        """,
        user_id,
        groups,
        roles,
    )
    return [
        {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "description": row["description"],
            "default_release_id": (
                str(row["default_release_id"]) if row["default_release_id"] else None
            ),
        }
        for row in rows
    ]


async def get_visible_release(
    pool: Pool, identity: ServiceIdentity, agent_id: str, version: str
) -> PublishedRelease:
    user_id, groups, roles = _subjects(identity)
    row = await pool.fetchrow(
        """
        SELECT r.release_id, r.agent_id, r.version, r.image, r.manifest, r.status
        FROM releases AS r
        WHERE r.agent_id = $1 AND r.version = $2
          AND EXISTS (
            SELECT 1 FROM access_grants AS g
            WHERE g.agent_id = r.agent_id AND g.revoked_at IS NULL
              AND g.permission IN ('discover', 'run', 'admin')
              AND ((g.subject_type = 'user' AND g.subject_id = $3)
                OR (g.subject_type = 'group' AND g.subject_id = ANY($4::text[]))
                OR (g.subject_type = 'role' AND g.subject_id = ANY($5::text[])))
          )
        """,
        agent_id,
        version,
        user_id,
        groups,
        roles,
    )
    if row is None:
        raise AccessError("release_not_found")
    return _from_row(row)


async def get_visible_release_by_id(
    pool: Pool, identity: ServiceIdentity, release_id: UUID
) -> PublishedRelease:
    user_id, groups, roles = _subjects(identity)
    row = await pool.fetchrow(
        """
        SELECT r.release_id, r.agent_id, r.version, r.image, r.manifest, r.status
        FROM releases AS r
        WHERE r.release_id = $1
          AND EXISTS (
            SELECT 1 FROM access_grants AS g
            WHERE g.agent_id = r.agent_id AND g.revoked_at IS NULL
              AND g.permission IN ('discover', 'run', 'admin')
              AND ((g.subject_type = 'user' AND g.subject_id = $2)
                OR (g.subject_type = 'group' AND g.subject_id = ANY($3::text[]))
                OR (g.subject_type = 'role' AND g.subject_id = ANY($4::text[])))
          )
        """,
        release_id,
        user_id,
        groups,
        roles,
    )
    if row is None:
        raise AccessError("release_not_found")
    return _from_row(row)


async def grant_access(
    pool: Pool,
    *,
    actor_id: str,
    idempotency_key: str,
    agent_id: str,
    subject_type: SubjectType,
    subject_id: str,
    permission: Permission,
) -> AccessGrant:
    if AGENT_ID_PATTERN.fullmatch(agent_id) is None or not 1 <= len(subject_id) <= 255:
        raise AccessError("grant_invalid")
    if (
        not 8 <= len(idempotency_key) <= 128
        or not idempotency_key.isascii()
        or not idempotency_key.isprintable()
    ):
        raise AccessError("idempotency_key_invalid")
    digest = request_sha256(
        {
            "agent_id": agent_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "permission": permission,
        }
    )
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{actor_id}:grant_access:{idempotency_key}",
        )
        stored = await connection.fetchrow(
            """
            SELECT i.request_sha256, g.* FROM idempotency_records AS i
            LEFT JOIN access_grants AS g ON g.grant_id = i.result_grant_id
            WHERE i.actor_id = $1 AND i.operation = 'grant_access' AND i.idempotency_key = $2
            """,
            actor_id,
            idempotency_key,
        )
        if stored is not None:
            if stored["request_sha256"] != digest:
                raise AccessError("idempotency_conflict")
            return _grant_from_row(stored)
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"grant:{agent_id}:{subject_type}:{subject_id}:{permission}",
        )
        if await connection.fetchrow("SELECT 1 FROM agents WHERE agent_id = $1", agent_id) is None:
            raise AccessError("agent_not_found")
        existing = await connection.fetchrow(
            """
            SELECT * FROM access_grants
            WHERE agent_id = $1 AND subject_type = $2 AND subject_id = $3
              AND permission = $4 AND revoked_at IS NULL
            """,
            agent_id,
            subject_type,
            subject_id,
            permission,
        )
        grant = _grant_from_row(existing) if existing else AccessGrant(
            uuid4(), agent_id, subject_type, subject_id, permission
        )
        if existing is None:
            await connection.execute(
                """INSERT INTO access_grants
                   (grant_id, agent_id, subject_type, subject_id, permission, granted_by)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                grant.grant_id, agent_id, subject_type, subject_id, permission, actor_id,
            )
            await connection.execute(
                """INSERT INTO access_grant_audit (audit_id, grant_id, action, actor_id)
                   VALUES ($1, $2, 'granted', $3)""",
                uuid4(), grant.grant_id, actor_id,
            )
        await connection.execute(
            """INSERT INTO idempotency_records
               (actor_id, operation, idempotency_key, request_sha256,
                response_status, result_grant_id)
               VALUES ($1, 'grant_access', $2, $3, 201, $4)""",
            actor_id, idempotency_key, digest, grant.grant_id,
        )
        return grant


async def revoke_access(
    pool: Pool, *, actor_id: str, idempotency_key: str, grant_id: UUID
) -> AccessGrant:
    if (
        not 8 <= len(idempotency_key) <= 128
        or not idempotency_key.isascii()
        or not idempotency_key.isprintable()
    ):
        raise AccessError("idempotency_key_invalid")
    digest = request_sha256({"grant_id": str(grant_id)})
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{actor_id}:revoke_access:{idempotency_key}",
        )
        stored = await connection.fetchrow(
            """
            SELECT i.request_sha256, g.* FROM idempotency_records AS i
            LEFT JOIN access_grants AS g ON g.grant_id = i.result_grant_id
            WHERE i.actor_id = $1 AND i.operation = 'revoke_access'
              AND i.idempotency_key = $2
            """,
            actor_id,
            idempotency_key,
        )
        if stored is not None:
            if stored["request_sha256"] != digest:
                raise AccessError("idempotency_conflict")
            return _grant_from_row(stored)
        row = await connection.fetchrow(
            "SELECT * FROM access_grants WHERE grant_id = $1 FOR UPDATE", grant_id
        )
        if row is None:
            raise AccessError("grant_not_found")
        if row["revoked_at"] is None:
            row = await connection.fetchrow(
                "UPDATE access_grants SET revoked_at = now() WHERE grant_id = $1 RETURNING *",
                grant_id,
            )
            await connection.execute(
                """INSERT INTO access_grant_audit (audit_id, grant_id, action, actor_id)
                   VALUES ($1, $2, 'revoked', $3)""",
                uuid4(), grant_id, actor_id,
            )
        grant = _grant_from_row(row)
        await connection.execute(
            """INSERT INTO idempotency_records
               (actor_id, operation, idempotency_key, request_sha256,
                response_status, result_grant_id)
               VALUES ($1, 'revoke_access', $2, $3, 200, $4)""",
            actor_id, idempotency_key, digest, grant_id,
        )
        return grant


def _grant_from_row(row: Any) -> AccessGrant:
    if row is None or row["grant_id"] is None:
        raise AccessError("idempotency_result_unavailable")
    return AccessGrant(
        row["grant_id"], row["agent_id"], row["subject_type"], row["subject_id"],
        row["permission"], row.get("revoked_at") is not None,
    )
