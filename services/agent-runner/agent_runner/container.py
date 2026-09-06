from __future__ import annotations

import asyncio
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


class ContainerBackend(Protocol):
    async def create(self, container: AttemptContainer) -> str: ...
    async def start(self, container_id: str) -> None: ...
    async def remove(self, container_id: str) -> None: ...
    async def exists(self, container_id: str) -> bool: ...


class PodmanBackend:
    """Rootless Podman backend. No caller-controlled runtime flags cross this boundary."""

    async def _run(self, *arguments: str, check: bool = True) -> str:
        process = await asyncio.create_subprocess_exec(
            "podman", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if check and process.returncode != 0:
            raise ContainerError(stderr.decode(errors="replace")[:500])
        return stdout.decode().strip()

    async def create(self, container: AttemptContainer) -> str:
        return await self._run(
            "create", "--name", container.name, "--user", "65532:65532", "--read-only",
            "--read-only-tmpfs=false", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16777216",
            "--cap-drop=all", "--security-opt=no-new-privileges", "--network=none",
            "--pids-limit", str(container.pids), "--memory", str(container.memory_bytes),
            "--cpus", str(container.cpu), "--ulimit", "nofile=64:64",
            "--env", f"PORFIRIUM_RUNTIME_URL={container.runtime_url}",
            "--env", f"PORFIRIUM_RUN_CAPABILITY={container.capability}", container.image,
        )

    async def start(self, container_id: str) -> None:
        await self._run("start", container_id)

    async def remove(self, container_id: str) -> None:
        await self._run("rm", "--force", "--time", "1", container_id)

    async def exists(self, container_id: str) -> bool:
        process = await asyncio.create_subprocess_exec(
            "podman", "container", "exists", container_id,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0

