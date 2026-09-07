import asyncio

import pytest

from agent_runner.capacity import CapacityLimits, has_capacity


class Connection:
    def __init__(self, global_active: int, user_active: int) -> None:
        self.counts = {"global_active": global_active, "user_active": user_active}
        self.locked = False

    async def execute(self, query: str) -> None:
        assert "pg_advisory_xact_lock" in query
        self.locked = True

    async def fetchrow(self, query: str, user_id: object) -> dict[str, int]:
        assert "count(*) FILTER" in query
        assert user_id == "user"
        assert self.locked
        return self.counts


def test_capacity_allows_only_below_both_limits() -> None:
    limits = CapacityLimits(global_runs=10, per_user_runs=2)
    assert asyncio.run(has_capacity(Connection(9, 1), "user", limits))
    assert not asyncio.run(has_capacity(Connection(10, 1), "user", limits))
    assert not asyncio.run(has_capacity(Connection(1, 2), "user", limits))


def test_capacity_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="positive"):
        CapacityLimits(global_runs=0, per_user_runs=0)
    with pytest.raises(ValueError, match="cannot exceed"):
        CapacityLimits(global_runs=2, per_user_runs=3)
