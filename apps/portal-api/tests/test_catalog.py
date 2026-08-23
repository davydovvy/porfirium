import json
from pathlib import Path

import pytest

from portal_api.catalog import load_manifest, manifest_digest, validate_manifest

MANIFEST_PATH = Path(__file__).parents[3] / "agents/tool-assistant/1.0.0/manifest.json"
GENERIC_MANIFEST_PATH = Path(__file__).parents[3] / "agents/tool-assistant/1.1.0/manifest.json"
CORRECTED_SEARCH_MANIFEST_PATH = (
    Path(__file__).parents[3] / "agents/tool-assistant/1.2.0/manifest.json"
)


def test_bundled_manifest_is_valid_and_digest_is_stable() -> None:
    manifest, digest = load_manifest(MANIFEST_PATH)
    assert manifest["agent"] == {
        "id": "tool-assistant",
        "version": "1.0.0",
        "name": "Tool Assistant",
        "description": "Durable read-only time and MTG catalog assistant",
    }
    assert digest == "sha256:e67130e726d431e143d53c56244b18cad043683ab29273bee0112529d2317ec2"
    assert digest == manifest_digest(manifest)


def test_manifest_rejects_unknown_fields() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    manifest["secret"] = "must never be accepted"
    with pytest.raises(ValueError, match="manifest_invalid"):
        validate_manifest(manifest)


def test_manifest_identity_must_match_package_path(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    with pytest.raises(ValueError, match="manifest_identity_path_mismatch"):
        validate_manifest(manifest, expected_path=tmp_path / "other-agent/9.9.9")


def test_generic_manifest_v2_is_valid() -> None:
    manifest, digest = load_manifest(GENERIC_MANIFEST_PATH)
    assert manifest["runtime"] == {"kind": "declarative", "contract_version": 1}
    assert digest == manifest_digest(manifest)


def test_corrected_search_manifest_is_valid() -> None:
    manifest, digest = load_manifest(CORRECTED_SEARCH_MANIFEST_PATH)
    assert manifest["agent"]["version"] == "1.2.0"
    assert digest == manifest_digest(manifest)


def test_generic_manifest_rejects_workflow_selection() -> None:
    manifest = json.loads(GENERIC_MANIFEST_PATH.read_text())
    manifest["runtime"]["workflow"] = "ArbitraryWorkflow"
    with pytest.raises(ValueError, match="manifest_invalid"):
        validate_manifest(manifest)
