import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from identity_delegation import main
from identity_delegation.main import ExchangeGrant
from identity_delegation.problems import DelegationProblem
from identity_delegation.store import GrantRecord
from identity_delegation.tokens import issue_token, verify_token


def identifiers() -> dict[str, UUID]:
    return {
        "grant": UUID(int=1),
        "user": UUID(int=2),
        "conversation": UUID(int=3),
        "release": UUID(int=4),
        "run": UUID(int=5),
        "attempt": UUID(int=6),
    }


def capability(ids: dict[str, UUID], tools: list[str]) -> str:
    return issue_token(
        {
            "audience": "agent-runtime-api",
            "exp": int(time.time()) + 60,
            "delegation_grant_id": str(ids["grant"]),
            "release_id": str(ids["release"]),
            "run_id": str(ids["run"]),
            "attempt_id": str(ids["attempt"]),
            "lease_epoch": 2,
            "tools": tools,
        },
        "run-secret",
    )


def test_attempt_capability_exchanges_only_pinned_tool_scope(monkeypatch) -> None:
    ids = identifiers()
    now = datetime.now(UTC)

    async def get_grant(*args, **kwargs):
        return GrantRecord(
            ids["grant"], ids["user"], ids["conversation"], ids["release"],
            ["tool:time_get_current_time"], now + timedelta(minutes=10), None, now,
        )

    monkeypatch.setattr(main, "get_grant", get_grant)
    main.app.state.pool = object()
    monkeypatch.setenv("RUN_CAPABILITY_SECRET", "run-secret")
    monkeypatch.setenv("DELEGATION_SIGNING_SECRET", "delegation-secret")
    body = ExchangeGrant(
        run_id=ids["run"],
        attempt_id=ids["attempt"],
        lease_epoch=2,
        audience="porfirium-mcp-gateway",
        scopes=["tool:time_get_current_time"],
    )

    result = asyncio.run(
        main.exchange_token(
            ids["grant"], body, None, f"Bearer {capability(ids, ['time_get_current_time'])}"
        )
    )

    claims = verify_token(result.access_token, "delegation-secret", "porfirium-mcp-gateway")
    assert claims["run_id"] == str(ids["run"])
    assert claims["scopes"] == ["tool:time_get_current_time"]


def test_attempt_capability_cannot_expand_pinned_tool_scope(monkeypatch) -> None:
    ids = identifiers()
    now = datetime.now(UTC)

    async def get_grant(*args, **kwargs):
        return GrantRecord(
            ids["grant"], ids["user"], ids["conversation"], ids["release"],
            ["tool:diagnostic_echo"], now + timedelta(minutes=10), None, now,
        )

    monkeypatch.setattr(main, "get_grant", get_grant)
    main.app.state.pool = object()
    monkeypatch.setenv("RUN_CAPABILITY_SECRET", "run-secret")
    body = ExchangeGrant(
        run_id=ids["run"],
        attempt_id=ids["attempt"],
        lease_epoch=2,
        audience="porfirium-mcp-gateway",
        scopes=["tool:diagnostic_echo"],
    )

    with pytest.raises(DelegationProblem, match="Tool is not granted"):
        asyncio.run(
            main.exchange_token(
                ids["grant"], body, None,
                f"Bearer {capability(ids, ['time_get_current_time'])}",
            )
        )


def test_cross_run_capability_is_rejected_before_grant_access(monkeypatch) -> None:
    ids = identifiers()
    monkeypatch.setenv("RUN_CAPABILITY_SECRET", "run-secret")
    body = ExchangeGrant(
        run_id=UUID(int=99), attempt_id=ids["attempt"], lease_epoch=2,
        audience="porfirium-mcp-gateway", scopes=["tool:time_get_current_time"],
    )

    with pytest.raises(DelegationProblem, match="Active run binding is invalid"):
        asyncio.run(
            main.exchange_token(
                ids["grant"], body, None,
                f"Bearer {capability(ids, ['time_get_current_time'])}",
            )
        )


def test_revoked_grant_blocks_a_new_tool_token(monkeypatch) -> None:
    ids = identifiers()
    now = datetime.now(UTC)

    async def get_grant(*args, **kwargs):
        return GrantRecord(
            ids["grant"], ids["user"], ids["conversation"], ids["release"],
            ["tool:time_get_current_time"], now + timedelta(minutes=10), now, now,
        )

    monkeypatch.setattr(main, "get_grant", get_grant)
    main.app.state.pool = object()
    monkeypatch.setenv("RUN_CAPABILITY_SECRET", "run-secret")
    body = ExchangeGrant(
        run_id=ids["run"], attempt_id=ids["attempt"], lease_epoch=2,
        audience="porfirium-mcp-gateway", scopes=["tool:time_get_current_time"],
    )

    with pytest.raises(DelegationProblem, match="Delegation grant is inactive"):
        asyncio.run(
            main.exchange_token(
                ids["grant"], body, None,
                f"Bearer {capability(ids, ['time_get_current_time'])}",
            )
        )
