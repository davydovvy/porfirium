from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from agent_registry.domain import AGENT_ID_PATTERN, request_sha256
from agent_registry.publication import Pool, PublishedRelease, _from_row


class LifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_key(key: str) -> None:
    if not 8 <= len(key) <= 128 or not key.isascii() or not key.isprintable():
        raise LifecycleError("idempotency_key_invalid")


async def set_default_release(
    pool: Pool,
    *,
    actor_id: str,
    idempotency_key: str,
    agent_id: str,
    release_id: UUID,
) -> dict[str, object]:
    _validate_key(idempotency_key)
    if AGENT_ID_PATTERN.fullmatch(agent_id) is None:
        raise LifecycleError("agent_not_found")
    digest = request_sha256({"agent_id": agent_id, "release_id": str(release_id)})
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{actor_id}:set_default_release:{idempotency_key}",
        )
        replay = await connection.fetchrow(
            """SELECT request_sha256, response_body FROM idempotency_records
               WHERE actor_id = $1 AND operation = 'set_default_release'
                 AND idempotency_key = $2""",
            actor_id,
            idempotency_key,
        )
        if replay is not None:
            if replay["request_sha256"] != digest:
                raise LifecycleError("idempotency_conflict")
            return _json_object(replay["response_body"])

        agent = await connection.fetchrow(
            """SELECT agent_id, name, description, default_release_id FROM agents
               WHERE agent_id = $1 FOR UPDATE""",
            agent_id,
        )
        if agent is None:
            raise LifecycleError("agent_not_found")
        release = await connection.fetchrow(
            "SELECT agent_id, status FROM releases WHERE release_id = $1 FOR UPDATE", release_id
        )
        if release is None or release["agent_id"] != agent_id:
            raise LifecycleError("release_not_found")
        if release["status"] != "published":
            raise LifecycleError("release_deprecated")
        previous = agent["default_release_id"]
        if previous != release_id:
            await connection.execute(
                "UPDATE agents SET default_release_id = $1, updated_at = now() WHERE agent_id = $2",
                release_id,
                agent_id,
            )
            await connection.execute(
                """INSERT INTO publication_audit
                   (audit_id, release_id, action, actor_id, details)
                   VALUES ($1, $2, 'default_release_changed', $3, $4::jsonb)""",
                uuid4(),
                release_id,
                actor_id,
                json.dumps(
                    {"previous_release_id": str(previous) if previous else None},
                    separators=(",", ":"),
                ),
            )
        response = {
            "agent_id": agent["agent_id"],
            "name": agent["name"],
            "description": agent["description"],
            "default_release_id": str(release_id),
        }
        await connection.execute(
            """INSERT INTO idempotency_records
               (actor_id, operation, idempotency_key, request_sha256, response_status,
                result_release_id, response_body)
               VALUES ($1, 'set_default_release', $2, $3, 200, $4, $5::jsonb)""",
            actor_id,
            idempotency_key,
            digest,
            release_id,
            json.dumps(response, separators=(",", ":")),
        )
        return response


async def deprecate_release(
    pool: Pool,
    *,
    actor_id: str,
    idempotency_key: str,
    release_id: UUID,
) -> PublishedRelease:
    _validate_key(idempotency_key)
    digest = request_sha256({"release_id": str(release_id)})
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{actor_id}:deprecate_release:{idempotency_key}",
        )
        replay = await connection.fetchrow(
            """SELECT i.request_sha256, r.release_id, r.agent_id, r.version, r.image,
                      r.manifest, r.status
               FROM idempotency_records AS i
               LEFT JOIN releases AS r ON r.release_id = i.result_release_id
               WHERE i.actor_id = $1 AND i.operation = 'deprecate_release'
                 AND i.idempotency_key = $2""",
            actor_id,
            idempotency_key,
        )
        if replay is not None:
            if replay["request_sha256"] != digest:
                raise LifecycleError("idempotency_conflict")
            if replay["release_id"] is None:
                raise LifecycleError("idempotency_result_unavailable")
            return _from_row(replay)

        identity = await connection.fetchrow(
            "SELECT agent_id FROM releases WHERE release_id = $1", release_id
        )
        if identity is None:
            raise LifecycleError("release_not_found")
        agent = await connection.fetchrow(
            "SELECT default_release_id FROM agents WHERE agent_id = $1 FOR UPDATE",
            identity["agent_id"],
        )
        row = await connection.fetchrow(
            """SELECT release_id, agent_id, version, image, manifest, status
               FROM releases WHERE release_id = $1 FOR UPDATE""",
            release_id,
        )
        if agent["default_release_id"] == release_id:
            raise LifecycleError("default_release_deprecation_forbidden")
        if row["status"] != "deprecated":
            row = await connection.fetchrow(
                """UPDATE releases SET status = 'deprecated', deprecated_by = $2,
                          deprecated_at = now()
                   WHERE release_id = $1
                   RETURNING release_id, agent_id, version, image, manifest, status""",
                release_id,
                actor_id,
            )
            await connection.execute(
                """INSERT INTO publication_audit (audit_id, release_id, action, actor_id)
                   VALUES ($1, $2, 'deprecated', $3)""",
                uuid4(),
                release_id,
                actor_id,
            )
        await connection.execute(
            """INSERT INTO idempotency_records
               (actor_id, operation, idempotency_key, request_sha256,
                response_status, result_release_id)
               VALUES ($1, 'deprecate_release', $2, $3, 200, $4)""",
            actor_id,
            idempotency_key,
            digest,
            release_id,
        )
        return _from_row(row)


def _json_object(value: Any) -> dict[str, object]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise LifecycleError("idempotency_result_unavailable")
    return decoded
