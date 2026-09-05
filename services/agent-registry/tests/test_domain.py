from __future__ import annotations

from copy import deepcopy

import pytest

from agent_registry.domain import PublicationValidationError, validate_publication

DIGEST = "sha256:" + "a" * 64
IMAGE = f"registry.local/example-agent@{DIGEST}"


@pytest.fixture
def manifest() -> dict[str, object]:
    return {
        "apiVersion": "porfirium.ai/v1",
        "kind": "Agent",
        "metadata": {
            "name": "example-agent",
            "version": "1.2.3",
            "displayName": "Example agent",
            "description": "A bounded test agent",
        },
        "spec": {
            "image": IMAGE,
            "entrypoint": "example_agent.main:graph",
            "sdk": ">=1.0,<2.0",
            "models": ["default"],
            "tools": ["time.current"],
            "configSchema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            },
            "resources": {"cpu": "500m", "memory": "256Mi", "timeoutSeconds": 300},
        },
    }


def provenance() -> dict[str, str]:
    return {
        "subjectDigest": DIGEST,
        "signature": "c2lnbmF0dXJl",
        "keyId": "ci-publication-key",
    }


def test_validates_documented_v1_manifest(manifest: dict[str, object]) -> None:
    release = validate_publication(manifest, IMAGE, provenance())

    assert release.agent_id == "example-agent"
    assert release.version == "1.2.3"
    assert release.image_digest == DIGEST
    assert len(release.manifest_sha256) == 64


@pytest.mark.parametrize(
    ("image", "code"),
    [
        ("registry.local/example-agent:latest", "image_invalid"),
        (f"registry.local/example-agent@sha256:{'A' * 64}", "image_invalid"),
    ],
)
def test_rejects_mutable_or_noncanonical_image(
    manifest: dict[str, object], image: str, code: str
) -> None:
    manifest = deepcopy(manifest)
    manifest["spec"]["image"] = image  # type: ignore[index]

    with pytest.raises(PublicationValidationError) as error:
        validate_publication(manifest, image, provenance())

    assert error.value.code == code


def test_rejects_image_different_from_manifest(manifest: dict[str, object]) -> None:
    other = f"registry.local/other@sha256:{'b' * 64}"

    with pytest.raises(PublicationValidationError) as error:
        validate_publication(manifest, other, provenance())

    assert error.value.code == "image_mismatch"


def test_rejects_incompatible_sdk(manifest: dict[str, object]) -> None:
    manifest = deepcopy(manifest)
    manifest["spec"]["sdk"] = ">=2.0,<3.0"  # type: ignore[index]

    with pytest.raises(PublicationValidationError) as error:
        validate_publication(manifest, IMAGE, provenance())

    assert error.value.code == "sdk_incompatible"


def test_rejects_provenance_for_another_digest(manifest: dict[str, object]) -> None:
    invalid_provenance = provenance()
    invalid_provenance["subjectDigest"] = "sha256:" + "b" * 64

    with pytest.raises(PublicationValidationError) as error:
        validate_publication(manifest, IMAGE, invalid_provenance)

    assert error.value.code == "provenance_invalid"


def test_rejects_unknown_manifest_fields(manifest: dict[str, object]) -> None:
    manifest["unexpected"] = True

    with pytest.raises(PublicationValidationError) as error:
        validate_publication(manifest, IMAGE, provenance())

    assert error.value.code == "manifest_invalid"
