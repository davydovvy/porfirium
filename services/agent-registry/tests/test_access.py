import asyncio
from uuid import uuid4

import pytest

from agent_registry.access import AccessError, get_visible_release, list_visible_agents
from agent_registry.auth import ServiceIdentity, authorize_admin
from agent_registry.problems import RegistryProblem


class ReadPool:
    def __init__(self, *, rows: list[dict[str, object]] | None = None, row: object = None) -> None:
        self.rows = rows or []
        self.row = row
        self.arguments: tuple[object, ...] = ()

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.arguments = args
        return self.rows

    async def fetchrow(self, query: str, *args: object) -> object:
        self.arguments = args
        return self.row

    def acquire(self) -> object:
        raise AssertionError("not used")


def test_discovery_passes_verified_user_group_and_role_subjects() -> None:
    release_id = uuid4()
    pool = ReadPool(
        rows=[
            {
                "agent_id": "example-agent",
                "name": "Example",
                "description": "Visible agent",
                "default_release_id": release_id,
            }
        ]
    )
    identity = ServiceIdentity(
        "user-1", "portal-bff", frozenset({"analyst"}), frozenset({"engineering"})
    )

    agents = asyncio.run(list_visible_agents(pool, identity))

    assert agents[0]["default_release_id"] == str(release_id)
    assert pool.arguments == ("user-1", ["engineering"], ["analyst"])


def test_hidden_release_is_indistinguishable_from_missing() -> None:
    identity = ServiceIdentity("user-1", "portal-bff", frozenset(), frozenset())

    with pytest.raises(AccessError, match="release_not_found"):
        asyncio.run(get_visible_release(ReadPool(), identity, "example-agent", "1.0.0"))


def test_grant_administration_requires_distinct_admin_role() -> None:
    publisher = ServiceIdentity(
        "publisher", "portal-bff", frozenset({"genai-agent-publisher"})
    )

    with pytest.raises(RegistryProblem) as error:
        authorize_admin(publisher)

    assert error.value.code == "grant_administration_forbidden"
