from __future__ import annotations

import asyncio
from uuid import uuid4

from agent_runner.container import PodmanBackend
from agent_runner.service import RunnerService


def test_reconciliation_preserves_full_id_container_and_removes_orphan(monkeypatch) -> None:
    recorded_id = "a" * 64
    orphan_id = "b" * 64
    recorded_network = f"porfirium-attempt-{uuid4()}"
    orphan_network = f"porfirium-attempt-{uuid4()}"
    removed = []

    class Pool:
        async def fetch(self, query):
            return [{"container_id": recorded_id, "network_name": recorded_network}]

    async def fake_run(self, *arguments, check=True):
        if arguments[0] == "ps":
            # Podman defaults to abbreviated IDs, while create returns the full ID.
            length = 64 if "--no-trunc" in arguments else 12
            return (
                f"{recorded_id[:length]} {recorded_network}\n"
                f"{orphan_id[:length]} {orphan_network}"
            )
        raise AssertionError(arguments)

    async def is_running(self, container_id):
        assert container_id == recorded_id
        return True

    async def remove(self, container_id, network_name):
        removed.append((container_id, network_name))

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    monkeypatch.setattr(PodmanBackend, "is_running", is_running)
    monkeypatch.setattr(PodmanBackend, "remove", remove)
    service = RunnerService(
        Pool(), PodmanBackend(), capability_secret="test-secret", runtime_url="runtime:50051"
    )

    assert asyncio.run(service.reconcile()) == 1
    assert removed == [(orphan_id, orphan_network)]

