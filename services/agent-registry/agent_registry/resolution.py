from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_registry.auth import ServiceIdentity
from agent_registry.domain import canonical_json, request_sha256
from agent_registry.publication import Pool


class ResolutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    run_id: UUID
    user_id: UUID
    conversation_id: UUID
    thread_id: UUID
    release_id: UUID
    delegation_grant_id: UUID
    trace_id: str
    configuration_revision_id: UUID | None = None
    starting_checkpoint_id: UUID | None = None

    def canonical_request(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "user_id": str(self.user_id),
            "conversation_id": str(self.conversation_id),
            "thread_id": str(self.thread_id),
            "release_id": str(self.release_id),
            "delegation_grant_id": str(self.delegation_grant_id),
            "configuration_revision_id": (
                str(self.configuration_revision_id) if self.configuration_revision_id else None
            ),
            "starting_checkpoint_id": (
                str(self.starting_checkpoint_id) if self.starting_checkpoint_id else None
            ),
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class SignedRunSpecification:
    specification_id: UUID
    run_id: UUID
    payload: dict[str, Any]
    payload_sha256: str
    signature: bytes
    key_id: str

    def contract_response(self) -> dict[str, object]:
        return {
            "specification_id": str(self.specification_id),
            "run_id": str(self.run_id),
            "payload": self.payload,
            "payload_sha256": self.payload_sha256,
            "signature": base64.b64encode(self.signature).decode(),
            "key_id": self.key_id,
        }


@dataclass(frozen=True, slots=True)
class RunSpecificationSigner:
    private_key: Ed25519PrivateKey
    key_id: str
    ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= len(self.key_id) <= 128 or not 30 <= self.ttl_seconds <= 3600:
            raise ValueError("invalid run specification signing configuration")

    def sign(self, payload: dict[str, Any]) -> tuple[str, bytes]:
        encoded = canonical_json(payload)
        return hashlib.sha256(encoded).hexdigest(), self.private_key.sign(encoded)


def load_run_signer(path: str, key_id: str, ttl_seconds: int = 300) -> RunSpecificationSigner:
    try:
        encoded = Path(path).read_text().strip()
        private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(encoded, validate=True))
        return RunSpecificationSigner(private_key, key_id, ttl_seconds)
    except (binascii.Error, OSError, ValueError, TypeError) as error:
        raise RuntimeError("invalid Registry run-signing key configuration") from error


async def resolve_run_specification(
    pool: Pool,
    signer: RunSpecificationSigner,
    identity: ServiceIdentity,
    request: ResolutionRequest,
    *,
    actor_id: str,
    idempotency_key: str,
) -> SignedRunSpecification:
    if identity.delegated_user_id != str(request.user_id):
        raise ResolutionError("user_context_mismatch")
    if not 8 <= len(idempotency_key) <= 128 or not idempotency_key.isascii():
        raise ResolutionError("idempotency_key_invalid")
    request_digest = request_sha256(request.canonical_request())
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"run:{request.run_id}"
        )
        replay = await connection.fetchrow(
            """SELECT i.request_sha256, s.* FROM idempotency_records AS i
               LEFT JOIN run_specifications AS s
                 ON s.specification_id = i.result_specification_id
               WHERE i.actor_id = $1 AND i.operation = 'resolve_run_specification'
                 AND i.idempotency_key = $2""",
            actor_id,
            idempotency_key,
        )
        if replay is not None:
            if replay["request_sha256"] != request_digest:
                raise ResolutionError("idempotency_conflict")
            return _from_row(replay)
        existing = await connection.fetchrow(
            "SELECT * FROM run_specifications WHERE run_id = $1", request.run_id
        )
        if existing is not None:
            if existing["request_sha256"] != request_digest:
                raise ResolutionError("run_specification_conflict")
            await connection.execute(
                """INSERT INTO idempotency_records
                   (actor_id, operation, idempotency_key, request_sha256, response_status,
                    result_specification_id)
                   VALUES ($1, 'resolve_run_specification', $2, $3, 200, $4)""",
                actor_id,
                idempotency_key,
                request_digest,
                existing["specification_id"],
            )
            return _from_row(existing)

        release = await _authorized_release(connection, identity, request)
        specification_id = uuid4()
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=signer.ttl_seconds)
        manifest = _json_object(release["manifest"])
        spec = _json_object(manifest["spec"])
        payload: dict[str, Any] = {
            "specification_version": 1,
            "specification_id": str(specification_id),
            **request.canonical_request(),
            "release": {
                "agent_id": release["agent_id"],
                "version": release["version"],
                "image": release["image"],
                "manifest_sha256": release["manifest_sha256"],
                "entrypoint": spec["entrypoint"],
                "sdk": spec["sdk"],
            },
            "requested_models": spec["models"],
            "requested_tools": spec["tools"],
            "resources": spec["resources"],
            "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
        payload_digest, signature = signer.sign(payload)
        await connection.execute(
            """INSERT INTO run_specifications
               (specification_id, run_id, release_id, user_id, request_sha256, payload,
                payload_sha256, signature, key_id, issued_at, expires_at)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11)""",
            specification_id,
            request.run_id,
            request.release_id,
            request.user_id,
            request_digest,
            json.dumps(payload, separators=(",", ":")),
            payload_digest,
            signature,
            signer.key_id,
            issued_at,
            expires_at,
        )
        await connection.execute(
            """INSERT INTO idempotency_records
               (actor_id, operation, idempotency_key, request_sha256, response_status,
                result_specification_id)
               VALUES ($1, 'resolve_run_specification', $2, $3, 200, $4)""",
            actor_id,
            idempotency_key,
            request_digest,
            specification_id,
        )
        return SignedRunSpecification(
            specification_id, request.run_id, payload, payload_digest, signature, signer.key_id
        )


async def _authorized_release(
    connection: Any, identity: ServiceIdentity, request: ResolutionRequest
) -> Any:
    row = await connection.fetchrow(
        """SELECT r.release_id, r.agent_id, r.version, r.image, r.manifest,
                  r.manifest_sha256, r.status
           FROM releases AS r
           WHERE r.release_id = $1 AND r.status = 'published'
             AND EXISTS (
               SELECT 1 FROM access_grants AS g
               WHERE g.agent_id = r.agent_id AND g.revoked_at IS NULL
                 AND g.permission IN ('run', 'admin')
                 AND ((g.subject_type = 'user' AND g.subject_id = $2)
                   OR (g.subject_type = 'group' AND g.subject_id = ANY($3::text[]))
                   OR (g.subject_type = 'role' AND g.subject_id = ANY($4::text[])))
             )""",
        request.release_id,
        str(request.user_id),
        sorted(identity.groups),
        sorted(identity.roles),
    )
    if row is None:
        raise ResolutionError("release_not_found")
    return row


def _from_row(row: Any) -> SignedRunSpecification:
    if row is None or row["specification_id"] is None:
        raise ResolutionError("idempotency_result_unavailable")
    return SignedRunSpecification(
        row["specification_id"],
        row["run_id"],
        _json_object(row["payload"]),
        row["payload_sha256"],
        bytes(row["signature"]),
        row["key_id"],
    )


def _json_object(value: Any) -> dict[str, Any]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise ResolutionError("stored_release_invalid")
    return decoded
