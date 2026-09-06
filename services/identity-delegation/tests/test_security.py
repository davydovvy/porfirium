import time

import pytest

from identity_delegation.policy import RunGrant, authorize_model, authorize_tool
from identity_delegation.problems import DelegationProblem
from identity_delegation.redaction import REDACTED, redact
from identity_delegation.tokens import issue_token, verify_token


def run_grant(*, cancelled: bool = False) -> RunGrant:
    return RunGrant("run", "attempt", 2, frozenset({"model-a"}),
                    frozenset({"weather.read"}), cancelled)


def test_model_and_both_tool_authorization_dimensions_are_required() -> None:
    authorize_model(run_grant(), "model-a")
    authorize_tool(run_grant(), "weather.read", frozenset({"tool:weather.read"}))
    with pytest.raises(DelegationProblem, match="tool_grant_missing"):
        authorize_tool(run_grant(), "filesystem.write", frozenset({"tool:filesystem.write"}))
    with pytest.raises(DelegationProblem, match="delegated_scope_missing"):
        authorize_tool(run_grant(), "weather.read", frozenset())


def test_cancellation_blocks_new_model_and_tool_work() -> None:
    with pytest.raises(DelegationProblem, match="run_cancelled"):
        authorize_model(run_grant(cancelled=True), "model-a")
    with pytest.raises(DelegationProblem, match="run_cancelled"):
        authorize_tool(run_grant(cancelled=True), "weather.read",
                       frozenset({"tool:weather.read"}))


def test_tokens_are_signed_audience_restricted_and_expiring() -> None:
    token = issue_token({"aud": "mcp", "exp": int(time.time()) + 30, "scopes": ["one"]}, "secret")
    assert verify_token(token, "secret", "mcp")["scopes"] == ["one"]
    with pytest.raises(DelegationProblem):
        verify_token(token, "secret", "llm")


def test_redaction_covers_structured_logs_events_traces_and_errors() -> None:
    token = "eyJabcdefghijk.abcdefghijklmnop.signature"
    channels = {
        "log": f"Authorization: Bearer {token}",
        "event": {"access_token": token},
        "trace": {"attributes": {"authorization": f"Bearer {token}"}},
        "error": f"provider failed access_token={token}",
    }
    rendered = repr(redact(channels))
    assert token not in rendered
    assert REDACTED in rendered
