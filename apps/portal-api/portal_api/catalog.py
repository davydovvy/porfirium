from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from jsonschema import Draft202012Validator

_COMMON_PROPERTIES: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "agent", "runtime", "model", "instructions", "tools", "limits"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer"},
        "agent": {
            "type": "object",
            "required": ["id", "version", "name", "description"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,62}$"},
                "version": {
                    "type": "string",
                    "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$",
                },
                "name": {"type": "string", "minLength": 1, "maxLength": 100},
                "description": {"type": "string", "minLength": 1, "maxLength": 500},
            },
        },
        "model": {
            "type": "object",
            "required": ["alias"],
            "additionalProperties": False,
            "properties": {"alias": {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,62}$"}},
        },
        "instructions": {"type": "string", "minLength": 1, "maxLength": 20_000},
        "tools": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[a-z0-9_]+-[a-z0-9_]+$"},
            "uniqueItems": True,
            "maxItems": 32,
        },
        "limits": {
            "type": "object",
            "required": [
                "max_iterations",
                "max_tool_calls_per_step",
                "max_tool_argument_bytes",
                "max_tool_result_bytes",
            ],
            "additionalProperties": False,
            "properties": {
                "max_iterations": {"type": "integer", "minimum": 1, "maximum": 16},
                "max_tool_calls_per_step": {"type": "integer", "minimum": 1, "maximum": 8},
                "max_tool_argument_bytes": {"type": "integer", "minimum": 256, "maximum": 65536},
                "max_tool_result_bytes": {"type": "integer", "minimum": 1024, "maximum": 1048576},
            },
        },
    },
}

MANIFEST_V1_SCHEMA: dict[str, object] = {
    **_COMMON_PROPERTIES,
    "properties": {
        **_COMMON_PROPERTIES["properties"],
        "schema_version": {"const": 1},
        "runtime": {
            "type": "object",
            "required": ["kind", "workflow"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "temporal"},
                "workflow": {"const": "PorfiriumToolAgentWorkflowV2"},
            },
        },
    },
}

MANIFEST_V2_SCHEMA: dict[str, object] = {
    **_COMMON_PROPERTIES,
    "properties": {
        **_COMMON_PROPERTIES["properties"],
        "schema_version": {"const": 2},
        "runtime": {
            "type": "object",
            "required": ["kind", "contract_version"],
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "declarative"},
                "contract_version": {"const": 1},
            },
        },
        "limits": {
            **_COMMON_PROPERTIES["properties"]["limits"],
            "required": [
                "max_iterations",
                "max_tool_calls_per_step",
                "max_tool_argument_bytes",
                "max_tool_result_bytes",
                "max_output_tokens",
            ],
            "properties": {
                **_COMMON_PROPERTIES["properties"]["limits"]["properties"],
                "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 32768},
            },
        },
    },
}

# Kept as a public compatibility name for callers which import it.
MANIFEST_SCHEMA = {"oneOf": [MANIFEST_V1_SCHEMA, MANIFEST_V2_SCHEMA]}
MAX_MANIFEST_BYTES = 32_768


def canonical_manifest(manifest: dict[str, object]) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def manifest_digest(manifest: dict[str, object]) -> str:
    return f"sha256:{hashlib.sha256(canonical_manifest(manifest)).hexdigest()}"


def validate_manifest(manifest: dict[str, object], *, expected_path: Path | None = None) -> str:
    schema = {1: MANIFEST_V1_SCHEMA, 2: MANIFEST_V2_SCHEMA}.get(manifest.get("schema_version"))
    if schema is None:
        raise ValueError("manifest_invalid:schema_version:unsupported schema version")
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=str)
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "manifest"
        raise ValueError(f"manifest_invalid:{location}:{errors[0].message}")
    agent = manifest["agent"]
    assert isinstance(agent, dict)
    if expected_path is not None:
        if expected_path.name != agent["version"] or expected_path.parent.name != agent["id"]:
            raise ValueError("manifest_identity_path_mismatch")
    return manifest_digest(manifest)


def load_manifest(path: Path) -> tuple[dict[str, object], str]:
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError("manifest_invalid:manifest:must be an object")
    digest = validate_manifest(manifest, expected_path=path.parent)
    return manifest, digest


def _reject_duplicate_key(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"candidate_invalid:duplicate_key:{key}")
        value[key] = item
    return value


def load_candidate(directory: Path) -> tuple[dict[str, object], bytes, str]:
    """Load one complete declarative filesystem candidate without following symlinks."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("candidate_invalid:directory")
    entries = list(directory.iterdir())
    if {entry.name for entry in entries} != {"manifest.json"}:
        raise ValueError("candidate_invalid:package_shape")
    path = entries[0]
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("candidate_invalid:manifest_file")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("candidate_invalid:manifest_too_large")
    try:
        manifest = json.loads(
            path.read_bytes().decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_key,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("candidate_invalid:json") from error
    if not isinstance(manifest, dict):
        raise ValueError("candidate_invalid:manifest_object")
    digest = validate_manifest(manifest, expected_path=directory)
    if manifest["schema_version"] != 2:
        raise ValueError("candidate_invalid:runtime_not_publishable")
    artifact = canonical_manifest(manifest)
    if len(artifact) > MAX_MANIFEST_BYTES:
        raise ValueError("candidate_invalid:manifest_too_large")
    return manifest, artifact, digest
