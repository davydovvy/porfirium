import asyncio

import pytest

from agent_runner.container import AttemptContainer, ContainerError, PodmanBackend

NETWORK = "porfirium-attempt-12345678-1234-1234-1234-123456789abc"


def test_podman_profile_is_fixed_and_fail_closed(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        calls.append(arguments)
        return "exact-container-id" if arguments[0] == "create" else ""

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    backend = PodmanBackend()
    container_id = asyncio.run(
        backend.create(
            AttemptContainer(
                "attempt-name", "example.invalid/agent@sha256:" + "a" * 64,
                "capability", "http://runtime:8104", 64 * 1024 * 1024, 0.5, 32,
                NETWORK,
            )
        )
    )

    assert container_id == "exact-container-id"
    assert calls[0] == ("network", "create", "--internal", NETWORK)
    assert calls[1] == (
        "network", "connect", "--alias", "runtime", NETWORK,
        "porfirium-agent-runtime-api",
    )
    create = calls[2]
    assert ("--network", NETWORK) == create[create.index("--network"):create.index("--network") + 2]
    assert ("--user", "65532:65532") == create[create.index("--user"):create.index("--user") + 2]
    assert "--read-only" in create
    assert "--read-only-tmpfs=false" in create
    assert ("--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216") == create[
        create.index("--tmpfs") : create.index("--tmpfs") + 2
    ]
    assert "--cap-drop=all" in create
    assert "--security-opt=no-new-privileges" in create
    assert ("--pids-limit", "32") == create[
        create.index("--pids-limit") : create.index("--pids-limit") + 2
    ]
    assert ("--memory", str(64 * 1024 * 1024)) == create[
        create.index("--memory") : create.index("--memory") + 2
    ]
    assert ("--cpus", "0.5") == create[create.index("--cpus") : create.index("--cpus") + 2]
    assert f"ai.porfirium.attempt-network={NETWORK}" in create
    assert [item for item in create if item == "--env"] == ["--env", "--env"]
    assert not any(
        "docker.sock" in item
        or "podman.sock" in item
        or item in {"--privileged", "--device", "--volume", "--mount"}
        for item in create
    )


def test_remove_addresses_only_recorded_container(monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        calls.append((arguments, check))
        return ""

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    asyncio.run(PodmanBackend().remove("recorded-id", NETWORK))

    assert calls == [
        (("rm", "--force", "--time", "1", "recorded-id"), False),
        (("network", "disconnect", "--force", NETWORK, "porfirium-agent-runtime-api"), False),
        (("network", "rm", NETWORK), False),
    ]


def test_remove_cleans_recorded_network_when_container_was_never_persisted(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        calls.append(arguments)
        return ""

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    asyncio.run(PodmanBackend().remove(None, NETWORK))

    assert calls == [
        ("network", "disconnect", "--force", NETWORK, "porfirium-agent-runtime-api"),
        ("network", "rm", NETWORK),
    ]


def test_rejects_untrusted_network_identity_before_running_podman(monkeypatch) -> None:
    called = False

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    with pytest.raises(ContainerError, match="invalid attempt network identity"):
        asyncio.run(
            PodmanBackend().create(
                AttemptContainer(
                    "attempt-name", "image", "capability", "http://runtime:8104",
                    64 * 1024 * 1024, 0.5, 32, "porfirium-attempt-not-a-uuid",
                )
            )
        )
    assert called is False


def test_running_state_requires_an_actively_running_container(monkeypatch) -> None:
    async def fake_exists(self, container_id: str) -> bool:
        assert container_id == "container-id"
        return True

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        assert arguments == ("inspect", "--format", "{{.State.Running}}", "container-id")
        return "false"

    monkeypatch.setattr(PodmanBackend, "exists", fake_exists)
    monkeypatch.setattr(PodmanBackend, "_run", fake_run)

    assert asyncio.run(PodmanBackend().is_running("container-id")) is False


def test_missing_container_is_not_running(monkeypatch) -> None:
    async def fake_exists(self, container_id: str) -> bool:
        assert container_id == "missing-container-id"
        return False

    async def unexpected_run(self, *arguments: str, check: bool = True) -> str:
        pytest.fail("missing containers must not be inspected")

    monkeypatch.setattr(PodmanBackend, "exists", fake_exists)
    monkeypatch.setattr(PodmanBackend, "_run", unexpected_run)

    assert asyncio.run(PodmanBackend().is_running("missing-container-id")) is False


def test_managed_lists_only_valid_labeled_attempt_containers(monkeypatch) -> None:
    network = NETWORK

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        assert arguments[:4] == ("ps", "--all", "--no-trunc", "--filter")
        return f"container-id {network}\ninvalid-line"

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)

    assert asyncio.run(PodmanBackend().managed()) == [("container-id", network)]


def test_managed_fails_closed_for_spoofed_network_label(monkeypatch) -> None:
    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        return "container-id ai.porfirium.attempt-network=foreign"

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    with pytest.raises(ContainerError, match="invalid attempt network identity"):
        asyncio.run(PodmanBackend().managed())
