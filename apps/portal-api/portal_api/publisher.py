from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .catalog import load_candidate
from .models import (
    Agent,
    AgentArtifact,
    AgentPublication,
    AgentToolGrant,
    AgentVersion,
    ModelAlias,
    ToolCatalogEntry,
)

ARTIFACT_MEDIA_TYPE = "application/vnd.porfirium.agent+json"


class PublicationError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Candidate:
    manifest: dict[str, object]
    artifact: bytes
    digest: str
    source: str

    @property
    def agent_id(self) -> str:
        return str(self.manifest["agent"]["id"])  # type: ignore[index]

    @property
    def version(self) -> str:
        return str(self.manifest["agent"]["version"])  # type: ignore[index]


def candidate_from_directory(directory: Path) -> Candidate:
    try:
        manifest, artifact, digest = load_candidate(directory)
    except ValueError as error:
        raise PublicationError("candidate_invalid", str(error)) from error
    return Candidate(manifest, artifact, digest, f"{directory.parent.name}/{directory.name}")


def offline_report(candidate: Candidate) -> dict[str, object]:
    return {
        "report_version": 1,
        "valid": True,
        "agent_id": candidate.agent_id,
        "version": candidate.version,
        "digest": candidate.digest,
        "artifact_size": len(candidate.artifact),
        "runtime": "declarative/1",
    }


async def platform_report(
    session: AsyncSession, candidate: Candidate
) -> tuple[dict[str, object], ModelAlias, list[ToolCatalogEntry]]:
    model_name = str(candidate.manifest["model"]["alias"])  # type: ignore[index]
    model = await session.scalar(
        select(ModelAlias).where(ModelAlias.alias == model_name, ModelAlias.enabled.is_(True))
    )
    if model is None:
        raise PublicationError("platform_resolution_failed", f"model_alias:{model_name}")

    tools: list[ToolCatalogEntry] = []
    for stable_name in candidate.manifest["tools"]:  # type: ignore[union-attr]
        matches = list(
            (
                await session.scalars(
                    select(ToolCatalogEntry).where(
                        ToolCatalogEntry.stable_name == stable_name,
                        ToolCatalogEntry.enabled.is_(True),
                    )
                )
            ).all()
        )
        if len(matches) != 1:
            raise PublicationError(
                "platform_resolution_failed", f"tool:{stable_name}:matches:{len(matches)}"
            )
        if not matches[0].read_only:
            raise PublicationError(
                "platform_resolution_failed", f"tool:{stable_name}:not_read_only"
            )
        tools.append(matches[0])

    report = {
        **offline_report(candidate),
        "model": {
            "id": str(model.id),
            "alias": model.alias,
            "provider": model.provider,
            "target": model.model,
        },
        "tools": [
            {
                "id": str(tool.id),
                "stable_name": tool.stable_name,
                "schema_version": tool.schema_version,
            }
            for tool in tools
        ],
    }
    return report, model, tools


async def publish(session: AsyncSession, candidate: Candidate) -> dict[str, object]:
    # Serialize each release identity so identical concurrent requests converge predictably.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:identity))"),
        {"identity": f"{candidate.agent_id}:{candidate.version}"},
    )
    existing = await session.scalar(
        select(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(Agent.slug == candidate.agent_id, AgentVersion.version == candidate.version)
    )
    if existing is not None:
        if existing.digest != candidate.digest:
            raise PublicationError("release_version_conflict")
        publication = await session.scalar(
            select(AgentPublication).where(AgentPublication.agent_version_id == existing.id)
        )
        return {
            "created": False,
            "agent_id": candidate.agent_id,
            "version": candidate.version,
            "digest": existing.digest,
            "release_id": str(existing.id),
            "publication_id": str(publication.id) if publication else None,
            "status": existing.status,
        }

    report, model, tools = await platform_report(session, candidate)
    digest_owner = await session.scalar(
        select(AgentVersion).where(AgentVersion.digest == candidate.digest)
    )
    if digest_owner is not None:
        raise PublicationError("release_digest_conflict")

    agent = await session.scalar(select(Agent).where(Agent.slug == candidate.agent_id))
    metadata = candidate.manifest["agent"]
    assert isinstance(metadata, dict)
    if agent is None:
        agent = Agent(
            slug=candidate.agent_id,
            name=str(metadata["name"]),
            description=str(metadata["description"]),
        )
        session.add(agent)
        await session.flush()

    artifact = AgentArtifact(
        digest=candidate.digest,
        media_type=ARTIFACT_MEDIA_TYPE,
        content=candidate.artifact,
        size_bytes=len(candidate.artifact),
    )
    session.add(artifact)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=candidate.version,
        digest=candidate.digest,
        artifact_id=artifact.id,
        manifest=candidate.manifest,
        model_alias_id=model.id,
        status="draft",
    )
    session.add(version)
    await session.flush()
    for tool in tools:
        session.add(
            AgentToolGrant(
                agent_version_id=version.id,
                tool_id=tool.id,
                policy_version=f"filesystem:{candidate.agent_id}:{candidate.version}",
            )
        )
    publication = AgentPublication(
        agent_version_id=version.id,
        provenance="filesystem",
        digest=candidate.digest,
        validation={**report, "source": candidate.source, "cli_contract_version": 1},
    )
    session.add(publication)
    await session.flush()
    version.status = "published"
    await session.flush()
    return {
        "created": True,
        "agent_id": candidate.agent_id,
        "version": candidate.version,
        "digest": candidate.digest,
        "release_id": str(version.id),
        "publication_id": str(publication.id),
        "status": version.status,
    }


async def release_status(
    session: AsyncSession, agent_id: str, version_number: str
) -> dict[str, object]:
    row = (
        await session.execute(
            select(Agent, AgentVersion, AgentArtifact, ModelAlias)
            .join(AgentVersion, AgentVersion.agent_id == Agent.id)
            .join(AgentArtifact, AgentArtifact.id == AgentVersion.artifact_id)
            .join(ModelAlias, ModelAlias.id == AgentVersion.model_alias_id)
            .where(Agent.slug == agent_id, AgentVersion.version == version_number)
        )
    ).one_or_none()
    if row is None:
        raise PublicationError("release_not_found")
    agent, release, artifact, model = row
    publication = await session.scalar(
        select(AgentPublication).where(AgentPublication.agent_version_id == release.id)
    )
    tools = list(
        (
            await session.scalars(
                select(ToolCatalogEntry)
                .join(AgentToolGrant, AgentToolGrant.tool_id == ToolCatalogEntry.id)
                .where(AgentToolGrant.agent_version_id == release.id)
                .order_by(ToolCatalogEntry.stable_name, ToolCatalogEntry.schema_version)
            )
        ).all()
    )
    return {
        "agent_id": agent.slug,
        "version": release.version,
        "status": release.status,
        "digest": release.digest,
        "artifact_size": artifact.size_bytes,
        "media_type": artifact.media_type,
        "provenance": publication.provenance if publication else None,
        "publication_id": str(publication.id) if publication else None,
        "published_at": release.published_at.isoformat(),
        "model": {"alias": model.alias, "provider": model.provider, "target": model.model},
        "tools": [
            {"stable_name": tool.stable_name, "schema_version": tool.schema_version}
            for tool in tools
        ],
    }
