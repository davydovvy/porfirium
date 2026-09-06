from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

from configuration_service.problems import ConfigurationProblem

MAX_CONFIGURATION_BYTES = 64 * 1024
MAX_DEPTH = 16


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_bounded(value: object, *, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ConfigurationProblem(422, "configuration_too_deep", "Configuration is too deep")
    if depth == 0 and len(canonical_json(value)) > MAX_CONFIGURATION_BYTES:
        raise ConfigurationProblem(413, "configuration_too_large", "Configuration is too large")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise ConfigurationProblem(
                    422, "configuration_invalid", "Invalid configuration key"
                )
            validate_bounded(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            validate_bounded(child, depth=depth + 1)


def merge_layers(*layers: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for layer in layers:
        for key, value in layer.items():
            if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
                result[key] = merge_layers(result[key], value)
            else:
                result[key] = value
    return result


def verify_schema_digest(schema: Mapping[str, Any], expected: str) -> None:
    if content_digest(schema) != expected:
        raise ConfigurationProblem(422, "schema_digest_mismatch", "Schema digest does not match")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        raise ConfigurationProblem(
            422, "schema_invalid", "Configuration schema is invalid"
        ) from error


def validate_effective(schema: Mapping[str, Any], values: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(values), key=lambda item: list(item.path)
    )
    if errors:
        path = ".".join(str(part) for part in errors[0].absolute_path)
        raise ConfigurationProblem(
            422,
            "configuration_schema_violation",
            "Configuration does not satisfy the release schema",
            {"path": path, "error_count": len(errors)},
        )
