import asyncio
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_registry.domain import canonical_json, validate_publication
from agent_registry.evidence import EvidenceVerifier, load_publication_keys
from agent_registry.problems import RegistryProblem

DIGEST = "sha256:" + "a" * 64
IMAGE = f"registry.local/example-agent@{DIGEST}"


def signed_release() -> tuple[object, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    provenance = {"subjectDigest": DIGEST, "keyId": "ci-key", "builder": "ci.example"}
    signature = private_key.sign(canonical_json(provenance))
    provenance["signature"] = base64.b64encode(signature).decode()
    manifest = {
        "apiVersion": "porfirium.ai/v1",
        "kind": "Agent",
        "metadata": {"name": "example-agent", "version": "1.0.0"},
        "spec": {
            "image": IMAGE,
            "entrypoint": "example_agent.main:graph",
            "sdk": ">=1.0,<2.0",
            "models": ["default"],
            "tools": [],
            "configSchema": {},
            "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
        },
    }
    return validate_publication(manifest, IMAGE, provenance), private_key


def verifier_for(
    private_key: Ed25519PrivateKey, *, observed_digest: str = DIGEST,
    allowed_builders: frozenset[str] = frozenset(),
) -> EvidenceVerifier:
    def registry(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v2/example-agent/manifests/{DIGEST}"
        return httpx.Response(200, headers={"Docker-Content-Digest": observed_digest})

    return EvidenceVerifier(
        httpx.AsyncClient(transport=httpx.MockTransport(registry)),
        registry_url="http://registry:5000",
        registry_host="registry.local",
        publication_keys={"ci-key": private_key.public_key()},
        allowed_builders=allowed_builders,
    )


def test_verifies_registry_digest_and_ed25519_provenance() -> None:
    release, private_key = signed_release()

    asyncio.run(verifier_for(private_key).verify(release))  # type: ignore[arg-type]


def test_rejects_registry_digest_mismatch() -> None:
    release, private_key = signed_release()

    with pytest.raises(RegistryProblem) as error:
        asyncio.run(
            verifier_for(private_key, observed_digest="sha256:" + "b" * 64).verify(release)  # type: ignore[arg-type]
        )

    assert error.value.code == "image_digest_mismatch"


def test_rejects_signature_from_another_key() -> None:
    release, _ = signed_release()

    with pytest.raises(RegistryProblem) as error:
        asyncio.run(verifier_for(Ed25519PrivateKey.generate()).verify(release))  # type: ignore[arg-type]

    assert error.value.code == "signature_invalid"


def test_rejects_provenance_from_untrusted_builder() -> None:
    release, private_key = signed_release()

    with pytest.raises(RegistryProblem) as error:
        asyncio.run(
            verifier_for(private_key, allowed_builders=frozenset({"trusted.example"})).verify(
                release  # type: ignore[arg-type]
            )
        )

    assert error.value.code == "builder_untrusted"


def test_loads_base64_encoded_public_keys() -> None:
    public_key = Ed25519PrivateKey.generate().public_key()
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    keys = load_publication_keys(json.dumps({"ci-key": base64.b64encode(raw).decode()}))

    assert set(keys) == {"ci-key"}
