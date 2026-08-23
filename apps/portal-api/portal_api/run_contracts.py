# ruff: noqa: E501
from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

RUN_SNAPSHOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["contract_version", "agent", "runtime", "instructions", "model", "tools", "limits"],
    "additionalProperties": False,
    "properties": {
        "contract_version": {"const": 1},
        "agent": {
            "type": "object",
            "required": ["id", "version", "version_id", "digest"],
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 63},
                "version": {"type": "string", "minLength": 1, "maxLength": 32},
                "version_id": {"type": "string", "format": "uuid"},
                "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            },
        },
        "runtime": {
            "type": "object", "required": ["kind", "contract_version"],
            "additionalProperties": False,
            "properties": {"kind": {"const": "declarative"}, "contract_version": {"const": 1}},
        },
        "instructions": {"type": "string", "minLength": 1, "maxLength": 20000},
        "model": {
            "type": "object", "required": ["alias", "provider", "model"],
            "additionalProperties": False,
            "properties": {
                "alias": {"type": "string", "minLength": 1, "maxLength": 63},
                "provider": {"type": "string", "minLength": 1, "maxLength": 64},
                "model": {"type": "string", "minLength": 1, "maxLength": 255},
            },
        },
        "tools": {
            "type": "array", "maxItems": 32, "uniqueItems": True,
            "items": {
                "type": "object", "required": ["stable_name", "server_name", "tool_name", "schema_version", "read_only", "definition", "policy_version"],
                "additionalProperties": False,
                "properties": {
                    "stable_name": {"type": "string", "minLength": 1, "maxLength": 255},
                    "server_name": {"type": "string", "minLength": 1, "maxLength": 128},
                    "tool_name": {"type": "string", "minLength": 1, "maxLength": 128},
                    "schema_version": {"type": "string", "minLength": 1, "maxLength": 32},
                    "read_only": {"const": True},
                    "definition": {"type": "object"},
                    "policy_version": {"type": "string", "minLength": 1, "maxLength": 64},
                },
            },
        },
        "limits": {
            "type": "object", "required": ["max_iterations", "max_tool_calls_per_step", "max_tool_argument_bytes", "max_tool_result_bytes", "max_output_tokens"],
            "additionalProperties": False,
            "properties": {
                "max_iterations": {"type": "integer", "minimum": 1, "maximum": 16},
                "max_tool_calls_per_step": {"type": "integer", "minimum": 1, "maximum": 8},
                "max_tool_argument_bytes": {"type": "integer", "minimum": 256, "maximum": 65536},
                "max_tool_result_bytes": {"type": "integer", "minimum": 1024, "maximum": 1048576},
                "max_output_tokens": {"type": "integer", "minimum": 1, "maximum": 32768},
            },
        },
    },
}


def validate_run_snapshot(snapshot: dict[str, object]) -> None:
    errors = sorted(Draft202012Validator(RUN_SNAPSHOT_SCHEMA).iter_errors(snapshot), key=str)
    if errors:
        path = ".".join(map(str, errors[0].absolute_path)) or "snapshot"
        raise ValueError(f"agent_run_snapshot_invalid:{path}")
    if len(json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()) > 262144:
        raise ValueError("agent_run_snapshot_too_large")
