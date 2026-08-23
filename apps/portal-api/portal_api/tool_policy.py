from __future__ import annotations

import json
from dataclasses import dataclass

from jsonschema import Draft202012Validator

POLICY_VERSION = "tool-assistant-v1.0.0"
AGENT_NAME = "tool_assistant_v1"
AGENT_VERSION = "1.0.0"
MAX_TOOL_ARGUMENT_BYTES = 4096


@dataclass(frozen=True)
class ToolPolicy:
    server_name: str
    tool_name: str
    external_name: str
    schema_version: str
    read_only: bool
    arguments_schema: dict[str, object]


def _object_schema(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS = {
    item.external_name: item
    for item in [
        ToolPolicy(
            "demo_time",
            "get_current_time",
            "demo_time-get_current_time",
            "1.0.0",
            True,
            _object_schema(
                {"timezone": {"type": "string", "minLength": 1, "maxLength": 128}},
                ["timezone"],
            ),
        ),
        ToolPolicy(
            "demo_time",
            "convert_time",
            "demo_time-convert_time",
            "1.0.0",
            True,
            _object_schema(
                {
                    "timestamp": {"type": "string", "minLength": 1, "maxLength": 64},
                    "from_timezone": {"type": "string", "minLength": 1, "maxLength": 128},
                    "to_timezone": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                ["timestamp", "from_timezone", "to_timezone"],
            ),
        ),
        ToolPolicy(
            "demo_mtg_catalog",
            "search_cards",
            "demo_mtg_catalog-search_cards",
            "1.0.0",
            True,
            _object_schema(
                {
                    "query": {"type": "string", "maxLength": 200},
                    "set_code": {"type": ["string", "null"], "maxLength": 8},
                    "colors": {
                        "type": ["array", "null"],
                        "items": {"type": "string", "enum": ["W", "U", "B", "R", "G"]},
                        "maxItems": 5,
                        "uniqueItems": True,
                    },
                    "card_type": {"type": ["string", "null"], "maxLength": 64},
                    "rarity": {
                        "type": ["string", "null"],
                        "enum": ["common", "uncommon", "rare", "mythic", None],
                    },
                    "min_price": {"type": ["string", "null"], "maxLength": 16},
                    "max_price": {"type": ["string", "null"], "maxLength": 16},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                ["query"],
            ),
        ),
        ToolPolicy(
            "demo_mtg_catalog",
            "get_card",
            "demo_mtg_catalog-get_card",
            "1.0.0",
            True,
            _object_schema(
                {"card_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                ["card_id"],
            ),
        ),
        ToolPolicy(
            "demo_mtg_catalog",
            "compare_cards",
            "demo_mtg_catalog-compare_cards",
            "1.0.0",
            True,
            _object_schema(
                {
                    "card_ids": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 64},
                        "minItems": 2,
                        "maxItems": 5,
                        "uniqueItems": True,
                    }
                },
                ["card_ids"],
            ),
        ),
        ToolPolicy(
            "demo_mtg_catalog",
            "list_sets",
            "demo_mtg_catalog-list_sets",
            "1.0.0",
            True,
            _object_schema({}, []),
        ),
    ]
}


def allowed_tool_names(granted: set[str] | None = None) -> tuple[str, ...]:
    return tuple(name for name in TOOLS if granted is None or name in granted)


def allowed_tool_definitions(granted: set[str] | None = None):
    from .gateways.contracts import ToolDefinition

    return tuple(
        ToolDefinition(
            name=item.external_name,
            description=f"Read-only {item.tool_name.replace('_', ' ')} operation.",
            input_schema=item.arguments_schema,
        )
        for item in TOOLS.values()
        if granted is None or item.external_name in granted
    )


def validate_tool_call(name: str, raw_arguments: str) -> tuple[ToolPolicy, dict[str, object]]:
    policy = TOOLS.get(name)
    if policy is None:
        raise ValueError("tool_not_allowlisted")
    if not policy.read_only:
        raise ValueError("tool_not_read_only")
    if len(raw_arguments.encode()) > MAX_TOOL_ARGUMENT_BYTES:
        raise ValueError("tool_arguments_too_large")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("tool_arguments_invalid_json") from exc
    errors = sorted(Draft202012Validator(policy.arguments_schema).iter_errors(arguments), key=str)
    if errors:
        raise ValueError("tool_arguments_schema_invalid")
    return policy, arguments
