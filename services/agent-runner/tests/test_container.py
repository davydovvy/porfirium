import asyncio

from agent_runner.container import AttemptContainer, PodmanBackend


def test_podman_profile_is_fixed_and_fail_closed(monkeypatch) -> None:
    captured: list[str] = []

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        captured.extend(arguments)
        return "exact-container-id"

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    backend = PodmanBackend()
    container_id = asyncio.run(
        backend.create(
            AttemptContainer(
                "attempt-name", "example.invalid/agent@sha256:" + "a" * 64,
                "capability", "http://runtime:8104", 64 * 1024 * 1024, 0.5, 32,
            )
        )
    )

    assert container_id == "exact-container-id"
    assert ["--user", "65532:65532"] == captured[3:5]
    assert "--read-only" in captured
    assert "--cap-drop=all" in captured
    assert "--security-opt=no-new-privileges" in captured
    assert "--network=none" in captured
    assert not any("docker.sock" in item or item == "--privileged" for item in captured)


def test_remove_addresses_only_recorded_container(monkeypatch) -> None:
    captured: tuple[str, ...] = ()

    async def fake_run(self, *arguments: str, check: bool = True) -> str:
        nonlocal captured
        captured = arguments
        return ""

    monkeypatch.setattr(PodmanBackend, "_run", fake_run)
    asyncio.run(PodmanBackend().remove("recorded-id"))

    assert captured == ("rm", "--force", "--time", "1", "recorded-id")
