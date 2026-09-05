#!/usr/bin/env python3
"""Validate Porfirium source contracts without service or network dependencies."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
TRACEPARENT = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AssertionError(f"invalid JSON: {path.relative_to(ROOT)}: {error}") from error


def resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for part in pointer.removeprefix("#/").split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def validate_instance(instance: Any, schema: dict[str, Any], path: str = "value") -> None:
    """Validate the deliberately small JSON Schema subset used by contract fixtures."""
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected] if expected else []
    type_checks = {
        "null": lambda value: value is None,
        "object": lambda value: isinstance(value, dict),
        "array": lambda value: isinstance(value, list),
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
    }
    if expected_types:
        assert any(type_checks[item](instance) for item in expected_types), (
            f"{path} has wrong type; expected {expected_types}"
        )
    if "const" in schema:
        assert instance == schema["const"], f"{path} must equal {schema['const']!r}"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path} is not an allowed enum value"
    if isinstance(instance, dict):
        required = set(schema.get("required", []))
        assert required <= instance.keys(), f"{path} lacks fields: {required - instance.keys()}"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert instance.keys() <= properties.keys(), (
                f"{path} has unknown fields: {instance.keys() - properties.keys()}"
            )
        if "maxProperties" in schema:
            assert len(instance) <= schema["maxProperties"], f"{path} has too many properties"
        for name, value in instance.items():
            if name in properties:
                validate_instance(value, properties[name], f"{path}.{name}")
    if isinstance(instance, list):
        if "maxItems" in schema:
            assert len(instance) <= schema["maxItems"], f"{path} has too many items"
        for index, value in enumerate(instance):
            validate_instance(value, schema.get("items", {}), f"{path}[{index}]")
    if isinstance(instance, str):
        assert len(instance) >= schema.get("minLength", 0), f"{path} is too short"
        assert len(instance) <= schema.get("maxLength", len(instance)), f"{path} is too long"
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], instance), f"{path} does not match its pattern"
        if schema.get("format") == "uuid":
            assert UUID.fullmatch(instance), f"{path} is not a canonical UUID"
        elif schema.get("format") == "date-time":
            datetime.fromisoformat(instance.replace("Z", "+00:00"))
        elif schema.get("format") == "uri":
            parsed = urlparse(instance)
            assert parsed.scheme and parsed.netloc, f"{path} is not an absolute URI"
    if isinstance(instance, int) and not isinstance(instance, bool):
        assert instance >= schema.get("minimum", instance), f"{path} is below minimum"
        assert instance <= schema.get("maximum", instance), f"{path} is above maximum"


def verify_refs(path: Path, document: Any, root: Any | None = None) -> None:
    root = document if root is None else root
    if isinstance(document, dict):
        reference = document.get("$ref")
        if isinstance(reference, str):
            if reference.startswith("#/"):
                resolve_pointer(root, reference)
            else:
                target_name = reference.split("#", 1)[0]
                target = (path.parent / target_name).resolve()
                assert target.is_relative_to(CONTRACTS), f"reference escapes contracts: {reference}"
                assert target.exists(), (
                    f"missing reference from {path.relative_to(ROOT)}: {reference}"
                )
                load(target)
        for value in document.values():
            verify_refs(path, value, root)
    elif isinstance(document, list):
        for value in document:
            verify_refs(path, value, root)


def verify_openapi(path: Path) -> None:
    document = load(path)
    assert document["openapi"].startswith("3.1."), f"unsupported OpenAPI version: {path}"
    assert document["info"]["version"].startswith("1."), f"API must be v1: {path}"
    operation_ids: set[str] = set()
    serialized = json.dumps(document, separators=(",", ":")).lower()
    assert "refresh_token" not in serialized, f"refresh token appears in API contract: {path.name}"
    assert "browser_token" not in serialized, f"browser token appears in API contract: {path.name}"
    for route, operations in document["paths"].items():
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation["operationId"]
            assert operation_id not in operation_ids, (
                f"duplicate operationId {operation_id}: {path}"
            )
            operation_ids.add(operation_id)
            if method in {"post", "put", "patch", "delete"} and not route.startswith("/health/"):
                parameters = operation.get("parameters", [])
                has_idempotency = any(
                    item.get("$ref", "").endswith("/IdempotencyKey") for item in parameters
                )
                assert has_idempotency, (
                    f"mutating operation lacks Idempotency-Key: {path.name} {method} {route}"
                )
            assert "default" in operation.get("responses", {}) or route.startswith("/health/"), (
                f"operation lacks default problem response: {path.name} {method} {route}"
            )
            for response in operation.get("responses", {}).values():
                if "$ref" in response:
                    continue
                content = response.get("content", {})
                if "text/event-stream" in content:
                    assert method == "get", f"SSE is read-only: {path.name} {method} {route}"
    verify_refs(path, document)


def verify_event_fixture(path: Path) -> None:
    event = load(path)
    validate_instance(event, load(CONTRACTS / "events" / "envelope-v1.schema.json"), "event")
    required = {
        "specversion", "type", "id", "source", "subject", "time", "user_id", "correlation_id",
        "causation_id", "traceparent", "schema_version", "data",
    }
    assert required <= event.keys(), f"event fixture lacks fields: {required - event.keys()}"
    assert event["specversion"] == "1.0" and event["schema_version"] == 1
    assert event["type"].endswith(".v1")
    for field in ("id", "user_id", "correlation_id", "causation_id"):
        assert UUID.fullmatch(event[field]), f"invalid {field}: {path}"
    assert TRACEPARENT.fullmatch(event["traceparent"]), f"invalid traceparent: {path}"
    serialized = json.dumps(event, separators=(",", ":"), ensure_ascii=False).lower()
    for prohibited in ("authorization", "bearer ", "refresh_token", "password"):
        assert prohibited not in serialized, f"prohibited credential marker in {path}: {prohibited}"


def verify_catalog() -> None:
    catalog = load(CONTRACTS / "events" / "catalog-v1.json")
    stream_prefixes = {
        "RUN_COMMANDS": "porfirium.run.command.",
        "RUN_EVENTS": "porfirium.run.event.",
        "CONVERSATION_EVENTS": "porfirium.conversation.event.",
        "MESSAGE_DELTAS": "porfirium.message.delta.",
        "USER_INPUT": "porfirium.input.command.",
        "AUDIT_EVENTS": "porfirium.audit.event.",
        "DEAD_LETTERS": "porfirium.dlq.",
    }
    catalogued_schemas: set[str] = set()
    for event_type, entry in catalog["events"].items():
        assert event_type.endswith(".v1")
        assert entry["stream"] in stream_prefixes, f"unknown stream for {event_type}"
        assert entry["subject"].startswith(stream_prefixes[entry["stream"]]), (
            f"subject is outside {entry['stream']}: {event_type}"
        )
        schema = CONTRACTS / "events" / entry["data_schema"]
        assert schema.exists(), f"missing data schema for {event_type}"
        catalogued_schemas.add(schema.name)
        load(schema)
        fixture_name = entry.get("fixture")
        if fixture_name:
            fixture = (CONTRACTS / "events" / fixture_name).resolve()
            assert fixture.is_relative_to(CONTRACTS)
            verify_event_fixture(fixture)
            event = load(fixture)
            assert event["type"] == event_type
            validate_instance(event["data"], load(schema), "event.data")
    source_schemas = {
        path.name for path in (CONTRACTS / "events").glob("*-v1.schema.json")
        if path.name != "envelope-v1.schema.json"
    }
    assert source_schemas == catalogued_schemas, (
        f"event schema catalog mismatch: missing={source_schemas - catalogued_schemas}, "
        f"unknown={catalogued_schemas - source_schemas}"
    )


def verify_http_fixtures() -> None:
    problem = load(CONTRACTS / "fixtures" / "http" / "problem-v1.json")
    schema = load(CONTRACTS / "http" / "problem-v1.schema.json")
    validate_instance(problem, schema, "problem")


def verify_protobuf() -> None:
    sources = sorted((CONTRACTS / "protobuf").rglob("*.proto"))
    assert sources, "no protobuf contracts found"
    with tempfile.TemporaryDirectory(prefix="porfirium-contracts-") as output:
        command = [
            "protoc", f"--proto_path={CONTRACTS / 'protobuf'}", "--proto_path=/usr/include",
            f"--descriptor_set_out={Path(output) / 'contracts.pb'}", "--include_imports",
            *map(str, sources),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)


def main() -> int:
    json_files = sorted(CONTRACTS.rglob("*.json"))
    assert json_files, "no JSON contracts found"
    for path in json_files:
        document = load(path)
        verify_refs(path, document)
    for path in sorted((CONTRACTS / "openapi").glob("*.json")):
        verify_openapi(path)
    verify_catalog()
    verify_http_fixtures()
    verify_protobuf()
    print(
        f"Contract verification passed: {len(json_files)} JSON documents, "
        f"{len(list((CONTRACTS / 'protobuf').rglob('*.proto')))} protobuf source."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Contract verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
