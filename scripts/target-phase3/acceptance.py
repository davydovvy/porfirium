from __future__ import annotations

import asyncio
import base64
import os
from uuid import uuid4

import asyncpg
import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_registry.access import grant_access, list_visible_agents, revoke_access
from agent_registry.auth import ServiceIdentity
from agent_registry.domain import canonical_json, validate_publication
from agent_registry.evidence import EvidenceVerifier
from agent_registry.lifecycle import deprecate_release, set_default_release
from agent_registry.publication import publish_release
from agent_registry.resolution import (
    ResolutionRequest,
    RunSpecificationSigner,
    resolve_run_specification,
)


def candidate(agent_id: str, version: str, digest: str) -> tuple[dict, str, dict]:
    image = f"registry:5000/porfirium-acceptance/{agent_id}@{digest}"
    manifest = {
        "apiVersion": "porfirium.ai/v1",
        "kind": "Agent",
        "metadata": {
            "name": agent_id,
            "version": version,
            "displayName": agent_id.replace("-", " ").title(),
            "description": f"Independent {agent_id} acceptance fixture",
        },
        "spec": {
            "image": image,
            "entrypoint": f"{agent_id.replace('-', '_')}.main:graph",
            "sdk": ">=1.0,<2.0",
            "models": ["default"],
            "tools": ["time.current"],
            "configSchema": {},
            "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
        },
    }
    provenance = {"subjectDigest": digest, "keyId": "acceptance-ci"}
    return manifest, image, provenance


async def verify_evidence(manifest: dict, image: str, provenance: dict) -> dict:
    private_key = Ed25519PrivateKey.generate()
    provenance["signature"] = base64.b64encode(
        private_key.sign(canonical_json(provenance))
    ).decode()
    release = validate_publication(manifest, image, provenance)

    async with httpx.AsyncClient() as client:
        verifier = EvidenceVerifier(
            client,
            registry_url="http://registry:5000",
            registry_host="registry:5000",
            publication_keys={"acceptance-ci": private_key.public_key()},
        )
        await verifier.verify(release)
    return provenance


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=4)
    assert pool is not None
    try:
        releases = []
        fixtures = [
            candidate("alpha-agent", "1.0.0", os.environ["ALPHA_V1_DIGEST"]),
            candidate("alpha-agent", "2.0.0", os.environ["ALPHA_V2_DIGEST"]),
            candidate("beta-agent", "1.0.0", os.environ["BETA_V1_DIGEST"]),
        ]
        for index, (manifest, image, provenance) in enumerate(fixtures):
            provenance = await verify_evidence(manifest, image, provenance)
            release = await publish_release(
                pool,
                actor_id="acceptance-publisher",
                idempotency_key=f"publication-{index}",
                manifest=manifest,
                image=image,
                provenance=provenance,
            )
            replay = await publish_release(
                pool,
                actor_id="acceptance-publisher",
                idempotency_key=f"publication-{index}",
                manifest=manifest,
                image=image,
                provenance=provenance,
            )
            assert replay == release
            releases.append(release)
        alpha_v1, alpha_v2, beta_v1 = releases

        user_id = uuid4()
        alpha_grant = await grant_access(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="grant-alpha-user",
            agent_id="alpha-agent",
            subject_type="user",
            subject_id=str(user_id),
            permission="run",
        )
        await grant_access(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="grant-beta-group",
            agent_id="beta-agent",
            subject_type="group",
            subject_id="operators",
            permission="discover",
        )
        revoked = await grant_access(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="grant-beta-outsider",
            agent_id="beta-agent",
            subject_type="user",
            subject_id="outsider",
            permission="discover",
        )
        await revoke_access(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="revoke-beta-outsider",
            grant_id=revoked.grant_id,
        )

        user = ServiceIdentity(str(user_id), "portal-bff", frozenset())
        group_user = ServiceIdentity("group-user", "portal-bff", frozenset(), frozenset({"operators"}))
        outsider = ServiceIdentity("outsider", "portal-bff", frozenset())
        assert [item["agent_id"] for item in await list_visible_agents(pool, user)] == ["alpha-agent"]
        assert [item["agent_id"] for item in await list_visible_agents(pool, group_user)] == ["beta-agent"]
        assert await list_visible_agents(pool, outsider) == []

        await set_default_release(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="default-alpha-v2",
            agent_id="alpha-agent",
            release_id=alpha_v2.release_id,
        )
        await set_default_release(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="default-beta-v1",
            agent_id="beta-agent",
            release_id=beta_v1.release_id,
        )

        resolver = ServiceIdentity(
            "runner-service",
            "agent-runner",
            frozenset({"genai-agent-run-resolver"}),
            frozenset(),
            str(user_id),
        )
        request = ResolutionRequest(
            run_id=uuid4(),
            user_id=user_id,
            conversation_id=uuid4(),
            thread_id=uuid4(),
            release_id=alpha_v1.release_id,
            delegation_grant_id=uuid4(),
            trace_id="d" * 32,
        )
        run_key = Ed25519PrivateKey.generate()
        signer = RunSpecificationSigner(run_key, "acceptance-run-key")
        specification = await resolve_run_specification(
            pool,
            signer,
            resolver,
            request,
            actor_id=resolver.subject,
            idempotency_key="resolve-alpha-run",
        )
        run_key.public_key().verify(specification.signature, canonical_json(specification.payload))
        assert specification.payload["release"]["image"] == alpha_v1.image

        await deprecate_release(
            pool,
            actor_id="acceptance-admin",
            idempotency_key="deprecate-alpha-v1",
            release_id=alpha_v1.release_id,
        )
        replay = await resolve_run_specification(
            pool,
            signer,
            resolver,
            request,
            actor_id=resolver.subject,
            idempotency_key="resolve-alpha-run-after-deprecation",
        )
        assert replay == specification

        async with pool.acquire() as connection:
            try:
                await connection.execute(
                    "UPDATE releases SET image = $2 WHERE release_id = $1",
                    alpha_v2.release_id,
                    beta_v1.image,
                )
            except asyncpg.PostgresError as error:
                assert "immutable release content" in str(error)
            else:
                raise AssertionError("database allowed immutable release content to change")
            assert await connection.fetchval(
                "SELECT count(*) FROM access_grant_audit WHERE grant_id = $1", alpha_grant.grant_id
            ) == 1

        print("PASS: independent immutable releases and idempotent publication")
        print("PASS: user/group grants, revocation, and access-filtered discovery")
        print("PASS: safe default/deprecation lifecycle and database immutability")
        print("PASS: delegated authorization and Runner-verifiable signed resolution")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
