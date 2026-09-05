from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from agent_registry.domain import ValidatedRelease, request_sha256, validate_publication


class Connection(Protocol):
    def transaction(self) -> Any: ...

    async def execute(self, query: str, *args: object) -> str: ...

    async def fetchrow(self, query: str, *args: object) -> Any: ...


class Pool(Protocol):
    def acquire(self) -> Any: ...

    async def fetch(self, query: str, *args: object) -> Any: ...

    async def fetchrow(self, query: str, *args: object) -> Any: ...


class PublicationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PublishedRelease:
    release_id: UUID
    agent_id: str
    version: str
    image: str
    manifest: dict[str, Any]
    status: str = "published"

    def contract_response(self) -> dict[str, object]:
        return {
            "release_id": str(self.release_id),
            "agent_id": self.agent_id,
            "version": self.version,
            "image": self.image,
            "manifest": self.manifest,
            "status": self.status,
        }


def _from_row(row: Any) -> PublishedRelease:
    manifest = row["manifest"]
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return PublishedRelease(
        release_id=row["release_id"],
        agent_id=row["agent_id"],
        version=row["version"],
        image=row["image"],
        manifest=manifest,
        status=row["status"],
    )


async def _existing_idempotent_result(
    connection: Connection,
    *,
    actor_id: str,
    key: str,
    digest: str,
) -> PublishedRelease | None:
    row = await connection.fetchrow(
        """
        SELECT i.request_sha256, r.release_id, r.agent_id, r.version, r.image,
               r.manifest, r.status
        FROM idempotency_records AS i
        LEFT JOIN releases AS r ON r.release_id = i.result_release_id
        WHERE i.actor_id = $1 AND i.operation = 'publish_release' AND i.idempotency_key = $2
        """,
        actor_id,
        key,
    )
    if row is None:
        return None
    if row["request_sha256"] != digest:
        raise PublicationError("idempotency_conflict")
    if row["release_id"] is None:
        raise PublicationError("idempotency_result_unavailable")
    return _from_row(row)


async def _store_release(
    connection: Connection, release: ValidatedRelease, *, actor_id: str, release_id: UUID
) -> None:
    agent = await connection.fetchrow(
        "SELECT name, description FROM agents WHERE agent_id = $1 FOR UPDATE", release.agent_id
    )
    if agent is None:
        await connection.execute(
            """
            INSERT INTO agents (agent_id, name, description)
            VALUES ($1, $2, $3)
            """,
            release.agent_id,
            release.name,
            release.description,
        )
    elif agent["name"] != release.name or agent["description"] != release.description:
        raise PublicationError("agent_metadata_conflict")

    conflict = await connection.fetchrow(
        """
        SELECT release_id, image
        FROM releases
        WHERE (agent_id = $1 AND version = $2) OR image = $3
        FOR UPDATE
        """,
        release.agent_id,
        release.version,
        release.image,
    )
    if conflict is not None:
        if conflict["image"] == release.image:
            raise PublicationError("image_already_published")
        raise PublicationError("release_version_conflict")

    await connection.execute(
        """
        INSERT INTO releases (
            release_id, agent_id, version, image, image_digest, manifest,
            manifest_sha256, provenance, sdk_constraint, published_by
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9, $10)
        """,
        release_id,
        release.agent_id,
        release.version,
        release.image,
        release.image_digest,
        json.dumps(release.manifest, separators=(",", ":")),
        release.manifest_sha256,
        json.dumps(release.provenance, separators=(",", ":")),
        release.sdk_constraint,
        actor_id,
    )
    await connection.execute(
        """
        INSERT INTO publication_audit (audit_id, release_id, action, actor_id, details)
        VALUES ($1, $2, 'published', $3, $4::jsonb)
        """,
        uuid4(),
        release_id,
        actor_id,
        json.dumps(
            {"image_digest": release.image_digest, "manifest_sha256": release.manifest_sha256},
            separators=(",", ":"),
        ),
    )


async def publish_release(
    pool: Pool,
    *,
    actor_id: str,
    idempotency_key: str,
    manifest: object,
    image: object,
    provenance: object,
) -> PublishedRelease:
    if not actor_id or len(actor_id) > 255:
        raise PublicationError("actor_invalid")
    if not 8 <= len(idempotency_key) <= 128 or not idempotency_key.isascii():
        raise PublicationError("idempotency_key_invalid")
    if not idempotency_key.isprintable():
        raise PublicationError("idempotency_key_invalid")

    release = validate_publication(manifest, image, provenance)
    digest = request_sha256(
        {"manifest": manifest, "image": image, "provenance": provenance}
    )
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"{actor_id}:publish_release:{idempotency_key}",
        )
        existing = await _existing_idempotent_result(
            connection, actor_id=actor_id, key=idempotency_key, digest=digest
        )
        if existing is not None:
            return existing

        # Serialize both identity and artifact uniqueness checks. PostgreSQL advisory locks avoid
        # leaking driver-specific unique-violation errors under concurrent publication.
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"agent:{release.agent_id}",
        )
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"image:{release.image}",
        )
        release_id = uuid4()
        await _store_release(connection, release, actor_id=actor_id, release_id=release_id)
        await connection.execute(
            """
            INSERT INTO idempotency_records (
                actor_id, operation, idempotency_key, request_sha256,
                response_status, result_release_id
            ) VALUES ($1, 'publish_release', $2, $3, 201, $4)
            """,
            actor_id,
            idempotency_key,
            digest,
            release_id,
        )
    return PublishedRelease(
        release_id=release_id,
        agent_id=release.agent_id,
        version=release.version,
        image=release.image,
        manifest=release.manifest,
    )
