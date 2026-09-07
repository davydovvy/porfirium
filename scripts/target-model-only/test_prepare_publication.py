import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from prepare_publication import canonical_json, prepare


def template() -> dict:
    return {
        "apiVersion": "porfirium.ai/v1",
        "kind": "Agent",
        "metadata": {"name": "model-only", "version": "1.0.0"},
        "spec": {"image": "${IMAGE}"},
    }


def test_renders_digest_and_signs_canonical_provenance() -> None:
    key = Ed25519PrivateKey.generate()
    encoded_key = base64.b64encode(key.private_bytes_raw()).decode()
    image = "registry.example/porfirium/model-only@sha256:" + "a" * 64

    result = prepare(template(), image, encoded_key, "release-key", "porfirium-release")

    assert result["image"] == image
    assert result["manifest"]["spec"]["image"] == image  # type: ignore[index]
    provenance = result["provenance"]
    signature = base64.b64decode(provenance.pop("signature"))  # type: ignore[union-attr]
    key.public_key().verify(signature, canonical_json(provenance))


def test_rejects_mutated_template_or_unpinned_image() -> None:
    key = base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode()
    with pytest.raises(ValueError, match="placeholder"):
        prepare({"spec": {"image": "latest"}}, "repo@sha256:" + "a" * 64, key, "key", "ci")
    with pytest.raises(ValueError, match="digest-pinned"):
        prepare(template(), "repo:latest", key, "key", "ci")
