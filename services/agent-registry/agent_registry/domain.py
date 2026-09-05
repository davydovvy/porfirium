from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
IMAGE_PATTERN = re.compile(r"^(?P<repository>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})$")
ENTRYPOINT_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
CPU_PATTERN = re.compile(r"^(?:[1-9][0-9]*m|(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)$")
MEMORY_PATTERN = re.compile(r"^[1-9][0-9]*(?:Ki|Mi|Gi)$")
SDK_COMPARATOR_PATTERN = re.compile(
    r"^(>=|>|<=|<|==)?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?$"
)

MAX_MANIFEST_BYTES = 64 * 1024
SUPPORTED_SDK_VERSION = (1, 0, 0)


class PublicationValidationError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(f"{code}:{field}:{message}")
        self.code = code
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class ValidatedRelease:
    agent_id: str
    name: str
    description: str
    version: str
    image: str
    image_digest: str
    manifest: dict[str, Any]
    manifest_sha256: str
    provenance: dict[str, Any]
    sdk_constraint: str


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def request_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PublicationValidationError("manifest_invalid", field, "must be an object")
    return value


def _string(value: object, field: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value) or len(value) > maximum:
        qualifier = f"a string no longer than {maximum} characters"
        raise PublicationValidationError("manifest_invalid", field, f"must be {qualifier}")
    return value


def _keys(value: dict[str, Any], field: str, required: set[str], optional: set[str]) -> None:
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise PublicationValidationError("manifest_invalid", field, f"missing {missing[0]}")
    if unknown:
        raise PublicationValidationError("manifest_invalid", field, f"unknown field {unknown[0]}")


def _validate_sdk_constraint(constraint: object) -> str:
    value = _string(constraint, "spec.sdk", maximum=64)
    comparisons = [item.strip() for item in value.split(",")]
    if not comparisons or any(not item for item in comparisons):
        raise PublicationValidationError("manifest_invalid", "spec.sdk", "invalid constraint")
    compatible = True
    for comparison in comparisons:
        match = SDK_COMPARATOR_PATTERN.fullmatch(comparison)
        if match is None:
            raise PublicationValidationError("manifest_invalid", "spec.sdk", "invalid constraint")
        operator = match.group(1) or "=="
        target = tuple(int(part or 0) for part in match.groups()[1:])
        compatible = compatible and {
            ">=": SUPPORTED_SDK_VERSION >= target,
            ">": SUPPORTED_SDK_VERSION > target,
            "<=": SUPPORTED_SDK_VERSION <= target,
            "<": SUPPORTED_SDK_VERSION < target,
            "==": SUPPORTED_SDK_VERSION == target,
        }[operator]
    if not compatible:
        raise PublicationValidationError(
            "sdk_incompatible", "spec.sdk", "does not include Registry protocol 1.0.0"
        )
    return value


def validate_publication(
    manifest_value: object, image_value: object, provenance_value: object
) -> ValidatedRelease:
    manifest = _object(manifest_value, "manifest")
    if len(canonical_json(manifest)) > MAX_MANIFEST_BYTES:
        raise PublicationValidationError("manifest_invalid", "manifest", "exceeds 65536 bytes")
    _keys(manifest, "manifest", {"apiVersion", "kind", "metadata", "spec"}, set())
    if manifest["apiVersion"] != "porfirium.ai/v1" or manifest["kind"] != "Agent":
        raise PublicationValidationError(
            "manifest_invalid", "manifest", "unsupported apiVersion or kind"
        )

    metadata = _object(manifest["metadata"], "metadata")
    _keys(metadata, "metadata", {"name", "version"}, {"displayName", "description"})
    agent_id = _string(metadata["name"], "metadata.name", maximum=63)
    if AGENT_ID_PATTERN.fullmatch(agent_id) is None:
        raise PublicationValidationError("manifest_invalid", "metadata.name", "invalid agent id")
    version = _string(metadata["version"], "metadata.version", maximum=32)
    if SEMVER_PATTERN.fullmatch(version) is None:
        raise PublicationValidationError("manifest_invalid", "metadata.version", "invalid SemVer")
    name = _string(metadata.get("displayName", agent_id), "metadata.displayName", maximum=100)
    description = _string(
        metadata.get("description", ""), "metadata.description", maximum=500, allow_empty=True
    )

    spec = _object(manifest["spec"], "spec")
    _keys(
        spec,
        "spec",
        {"image", "entrypoint", "sdk", "models", "tools", "configSchema", "resources"},
        {"configDefaults"},
    )
    image = _string(image_value, "image", maximum=512)
    manifest_image = _string(spec["image"], "spec.image", maximum=512)
    match = IMAGE_PATTERN.fullmatch(image)
    if match is None:
        raise PublicationValidationError("image_invalid", "image", "must be digest-pinned")
    if manifest_image != image:
        raise PublicationValidationError("image_mismatch", "spec.image", "must equal image")
    entrypoint = _string(spec["entrypoint"], "spec.entrypoint", maximum=255)
    if ENTRYPOINT_PATTERN.fullmatch(entrypoint) is None:
        raise PublicationValidationError(
            "manifest_invalid", "spec.entrypoint", "invalid entrypoint"
        )
    sdk_constraint = _validate_sdk_constraint(spec["sdk"])

    for field, maximum in (("models", 16), ("tools", 64)):
        values = spec[field]
        if not isinstance(values, list) or len(values) > maximum or len(values) != len(set(values)):
            raise PublicationValidationError("manifest_invalid", f"spec.{field}", "invalid list")
        invalid_capability = any(
            not isinstance(item, str) or CAPABILITY_PATTERN.fullmatch(item) is None
            for item in values
        )
        if invalid_capability:
            raise PublicationValidationError(
                "manifest_invalid", f"spec.{field}", "invalid capability name"
            )

    config_schema = _object(spec["configSchema"], "spec.configSchema")
    if config_schema.get("$schema") not in (None, "https://json-schema.org/draft/2020-12/schema"):
        raise PublicationValidationError(
            "manifest_invalid", "spec.configSchema.$schema", "unsupported JSON Schema dialect"
        )
    if "configDefaults" in spec:
        _object(spec["configDefaults"], "spec.configDefaults")

    resources = _object(spec["resources"], "spec.resources")
    _keys(resources, "spec.resources", {"cpu", "memory", "timeoutSeconds"}, set())
    cpu = _string(resources["cpu"], "spec.resources.cpu", maximum=16)
    memory = _string(resources["memory"], "spec.resources.memory", maximum=16)
    timeout = resources["timeoutSeconds"]
    if CPU_PATTERN.fullmatch(cpu) is None or MEMORY_PATTERN.fullmatch(memory) is None:
        raise PublicationValidationError("manifest_invalid", "spec.resources", "invalid resource")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
        raise PublicationValidationError(
            "manifest_invalid", "spec.resources.timeoutSeconds", "must be between 1 and 3600"
        )

    provenance = _object(provenance_value, "provenance")
    _keys(provenance, "provenance", {"subjectDigest", "signature", "keyId"}, {"builder"})
    digest = match.group("digest")
    if provenance["subjectDigest"] != digest:
        raise PublicationValidationError(
            "provenance_invalid", "provenance.subjectDigest", "must equal image digest"
        )
    signature = _string(provenance["signature"], "provenance.signature", maximum=8192)
    try:
        if not base64.b64decode(signature, validate=True):
            raise ValueError
    except (binascii.Error, ValueError):
        raise PublicationValidationError(
            "provenance_invalid", "provenance.signature", "must be non-empty base64"
        ) from None
    _string(provenance["keyId"], "provenance.keyId", maximum=128)
    if "builder" in provenance:
        _string(provenance["builder"], "provenance.builder", maximum=255)

    return ValidatedRelease(
        agent_id=agent_id,
        name=name,
        description=description,
        version=version,
        image=image,
        image_digest=digest,
        manifest=manifest,
        manifest_sha256=request_sha256(manifest),
        provenance=provenance,
        sdk_constraint=sdk_constraint,
    )
