import json

import pytest

from portal_api.tool_policy import allowed_tool_names, validate_tool_call


def test_allows_reviewed_read_only_tool() -> None:
    policy, arguments = validate_tool_call(
        "demo_time-get_current_time", json.dumps({"timezone": "Europe/Moscow"})
    )
    assert policy.read_only is True
    assert arguments == {"timezone": "Europe/Moscow"}


@pytest.mark.parametrize(
    ("name", "arguments", "reason"),
    [
        ("phase0_diagnostic-echo", '{"message":"no"}', "tool_not_allowlisted"),
        ("fabricated-delete_all", "{}", "tool_not_allowlisted"),
        ("demo_time-get_current_time ", '{"timezone":"UTC"}', "tool_not_allowlisted"),
        ("demo_time-get_current_time", "not-json", "tool_arguments_invalid_json"),
        ("demo_time-get_current_time", "{}", "tool_arguments_schema_invalid"),
        (
            "demo_time-get_current_time",
            '{"timezone":"UTC","unexpected":true}',
            "tool_arguments_schema_invalid",
        ),
    ],
)
def test_fails_closed(name: str, arguments: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        validate_tool_call(name, arguments)


def test_policy_contains_only_phase4_tools() -> None:
    assert set(allowed_tool_names()) == {
        "demo_time-get_current_time",
        "demo_time-convert_time",
        "demo_mtg_catalog-search_cards",
        "demo_mtg_catalog-get_card",
        "demo_mtg_catalog-compare_cards",
        "demo_mtg_catalog-list_sets",
    }


def test_rejects_oversized_arguments_before_schema_validation() -> None:
    arguments = json.dumps({"timezone": "A" * 5000})
    with pytest.raises(ValueError, match="tool_arguments_too_large"):
        validate_tool_call("demo_time-get_current_time", arguments)
