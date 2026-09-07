from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol


class ContainerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AttemptContainer:
    name: str
    image: str
    capability: str
    runtime_url: str
    memory_bytes: int
    cpu: float
    pids: int
    network_name: str


class ContainerBackend(Protocol):
    async def create(self, container: AttemptContainer) -> str: ...
    async def start(self, container_id: str) -> None: ...
    async def remove(self, container_id: str | None, network_name: str) -> None: ...
    async def exists(self, container_id: str) -> bool: ...
    async def is_running(self, container_id: str) -> bool: ...
    async def managed(self) -> list[tuple[str, str]]: ...


class PodmanBackend:
    """Rootless Podman backend. No caller-controlled runtime flags cross this boundary."""

    def __init__(self, runtime_container: str = "porfirium-agent-runtime-api") -> None:
        self.runtime_container = runtime_container

    async def _run(self, *arguments: str, check: bool = True) -> str:
        process = await asyncio.create_subprocess_exec(
            "podman", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if check and process.returncode != 0:
            raise ContainerError(stderr.decode(errors="replace")[:500])
        return stdout.decode().strip()

    async def create(self, container: AttemptContainer) -> str:
        self._validate_network(container.network_name)
        await self._run("network", "create", "--internal", container.network_name)
        try:
            await self._run(
                "network", "connect", "--alias", "runtime", container.network_name,
                self.runtime_container,
            )
            return await self._run(
                "create", "--name", container.name,
                "--label", f"ai.porfirium.attempt-network={container.network_name}",
                "--user", "65532:65532", "--read-only", "--read-only-tmpfs=false",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216",
                "--cap-drop=all", "--security-opt=no-new-privileges",
                "--network", container.network_name,
                "--pids-limit", str(container.pids), "--memory", str(container.memory_bytes),
                "--cpus", str(container.cpu), "--ulimit", "nofile=64:64",
                "--env", f"PORFIRIUM_RUNTIME_URL={container.runtime_url}",
                "--env", f"PORFIRIUM_RUN_CAPABILITY={container.capability}", container.image,
            )
        except Exception:
            await self._cleanup_network(container.network_name)
            raise

    async def start(self, container_id: str) -> None:
        await self._run("start", container_id)

    async def remove(self, container_id: str | None, network_name: str) -> None:
        self._validate_network(network_name)
        if container_id:
            await self._run("rm", "--force", "--time", "1", container_id, check=False)
        await self._cleanup_network(network_name)

    async def exists(self, container_id: str) -> bool:
        process = await asyncio.create_subprocess_exec(
            "podman", "container", "exists", container_id,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0

    async def is_running(self, container_id: str) -> bool:
        value = await self._run("inspect", "--format", "{{.State.Running}}", container_id)
        return value == "true"

    async def managed(self) -> list[tuple[str, str]]:
        output = await self._run(
            "ps", "--all", "--filter", "label=ai.porfirium.attempt-network",
            "--format", '{{.ID}} {{.Label "ai.porfirium.attempt-network"}}',
        )
        managed: list[tuple[str, str]] = []
        for line in output.splitlines():
            container_id, separator, network = line.partition(" ")
            if not separator:
                continue
            self._validate_network(network)
            managed.append((container_id, network))
        return managed

    async def _cleanup_network(self, network: str) -> None:
        await self._run(
            "network", "disconnect", "--force", network, self.runtime_container, check=False
        )
        await self._run("network", "rm", network, check=False)

    @staticmethod
    def _validate_network(network: str) -> None:
        if re.fullmatch(
            r"porfirium-attempt-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}",
            network,
        ) is None:
            raise ContainerError("invalid attempt network identity")
