import pytest

from agent_runner.main import _require_operator
from agent_runner.service import RunnerError


def test_operator_authentication_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("RUNNER_OPERATOR_TOKEN", raising=False)
    with pytest.raises(RunnerError) as error:
        _require_operator("Bearer anything")
    assert error.value.code == "operator_auth_unavailable"


def test_operator_authentication_rejects_wrong_token(monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_OPERATOR_TOKEN", "correct")
    with pytest.raises(RunnerError) as error:
        _require_operator("Bearer wrong")
    assert error.value.code == "operator_forbidden"


def test_operator_authentication_accepts_scoped_token(monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_OPERATOR_TOKEN", "correct")
    _require_operator("Bearer correct")
