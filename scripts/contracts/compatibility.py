#!/usr/bin/env python3
"""Build or check the stable semantic surface of v1 JSON contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts"
BASELINE = CONTRACTS / "compatibility" / "v1-baseline.json"


def schema_surface(schema: Any, prefix: str = "$") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(schema, dict):
        return result
    keywords = (
        "type", "const", "pattern", "format", "minimum", "maximum", "minLength", "maxLength"
    )
    for keyword in keywords:
        if keyword in schema:
            result[f"{prefix}:{keyword}"] = schema[keyword]
    if "required" in schema:
        result[f"{prefix}:required"] = sorted(schema["required"])
    if "enum" in schema:
        result[f"{prefix}:enum"] = sorted(schema["enum"], key=str)
    for name, child in schema.get("properties", {}).items():
        result.update(schema_surface(child, f"{prefix}.{name}"))
    for index, child in enumerate(schema.get("allOf", [])):
        result.update(schema_surface(child, f"{prefix}.allOf[{index}]"))
    if isinstance(schema.get("items"), dict):
        result.update(schema_surface(schema["items"], f"{prefix}[]"))
    return result


def current_surface() -> dict[str, Any]:
    surface: dict[str, Any] = {"format_version": 1, "documents": {}}
    for path in sorted((CONTRACTS / "events").glob("*.schema.json")):
        relative = str(path.relative_to(CONTRACTS))
        surface["documents"][relative] = schema_surface(json.loads(path.read_text()))
    for path in sorted((CONTRACTS / "http").glob("*.schema.json")):
        relative = str(path.relative_to(CONTRACTS))
        surface["documents"][relative] = schema_surface(json.loads(path.read_text()))
    for path in sorted((CONTRACTS / "openapi").glob("*.json")):
        document = json.loads(path.read_text())
        api: dict[str, Any] = {}
        for route, methods in document["paths"].items():
            for method, operation in methods.items():
                if method in {"get", "post", "put", "patch", "delete"}:
                    api[f"{method.upper()} {route}"] = {
                        "operationId": operation["operationId"],
                        "responses": sorted(operation["responses"]),
                    }
        for name, schema in document.get("components", {}).get("schemas", {}).items():
            api[f"schema:{name}"] = schema_surface(schema)
        surface["documents"][str(path.relative_to(CONTRACTS))] = api
    return surface


def compatible(old: Any, new: Any, path: str = "$") -> list[str]:
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [f"{path} changed kind"]
        errors: list[str] = []
        for key, value in old.items():
            if key not in new:
                errors.append(f"{path}.{key} was removed")
            else:
                errors.extend(compatible(value, new[key], f"{path}.{key}"))
        return errors
    extensible_list = path.endswith(":enum") or path.endswith(".responses")
    if extensible_list and isinstance(old, list) and isinstance(new, list):
        return [] if set(map(str, old)) <= set(map(str, new)) else [f"{path} removed enum values"]
    return [] if old == new else [f"{path} changed from {old!r} to {new!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    current = current_surface()
    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        print("Wrote v1 compatibility baseline.")
        return 0
    if not BASELINE.exists():
        raise SystemExit("v1 compatibility baseline is missing")
    errors = compatible(json.loads(BASELINE.read_text()), current)
    if errors:
        raise SystemExit("incompatible v1 contract changes:\n" + "\n".join(errors))
    print("V1 compatibility check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
