import pytest

from configuration_service.domain import (
    content_digest,
    merge_layers,
    validate_bounded,
    validate_effective,
    verify_schema_digest,
)
from configuration_service.problems import ConfigurationProblem


def test_configuration_precedence_is_recursive_and_deterministic() -> None:
    defaults = {"model": {"name": "small", "temperature": 0.2}, "limit": 10}
    user = {"model": {"temperature": 0.4}}
    conversation = {"limit": 3}
    assert merge_layers(defaults, user, conversation) == {
        "model": {"name": "small", "temperature": 0.4},
        "limit": 3,
    }
    assert merge_layers(defaults, user, conversation) == merge_layers(defaults, user, conversation)


def test_schema_digest_and_effective_values_are_validated() -> None:
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"limit": {"type": "integer", "maximum": 10}},
              "required": ["limit"]}
    verify_schema_digest(schema, content_digest(schema))
    validate_effective(schema, {"limit": 3})
    with pytest.raises(ConfigurationProblem, match="configuration_schema_violation"):
        validate_effective(schema, {"limit": 11})


def test_configuration_bounds_reject_excessive_depth() -> None:
    value: dict[str, object] = {}
    cursor = value
    for _ in range(18):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ConfigurationProblem, match="configuration_too_deep"):
        validate_bounded(value)
