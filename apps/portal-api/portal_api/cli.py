from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from .db import session_factory
from .publisher import (
    PublicationError,
    candidate_from_directory,
    offline_report,
    platform_report,
    publish,
    release_status,
)

EXIT_CODES = {
    "candidate_invalid": 2,
    "platform_resolution_failed": 3,
    "release_version_conflict": 4,
    "release_digest_conflict": 4,
    "release_not_found": 5,
    "dependency_failure": 6,
    "internal_failure": 10,
}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="porfirium")
    groups = root.add_subparsers(dest="group", required=True)
    agents = groups.add_parser("agents")
    commands = agents.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("directory", type=Path)
    validate.add_argument("--platform", action="store_true")
    validate.add_argument("--json", action="store_true", dest="as_json")
    publication = commands.add_parser("publish")
    publication.add_argument("directory", type=Path)
    publication.add_argument("--json", action="store_true", dest="as_json")
    status = commands.add_parser("status")
    status.add_argument("release")
    status.add_argument("--json", action="store_true", dest="as_json")
    return root


def emit(value: dict[str, object], as_json: bool) -> None:
    envelope = {"contract_version": 1, **value}
    if as_json:
        print(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
        return
    for key, item in envelope.items():
        if isinstance(item, dict | list):
            item = json.dumps(item, sort_keys=True, separators=(",", ":"))
        print(f"{key}: {item}")


async def run(args: argparse.Namespace) -> None:
    if args.command == "validate":
        candidate = candidate_from_directory(args.directory)
        report = offline_report(candidate)
        if args.platform:
            async with session_factory() as session:
                report, _, _ = await platform_report(session, candidate)
        emit(report, args.as_json)
        return
    if args.command == "publish":
        candidate = candidate_from_directory(args.directory)
        async with session_factory() as session, session.begin():
            result = await publish(session, candidate)
        emit(result, args.as_json)
        return
    if args.command == "status":
        if args.release.count(":") != 1:
            raise PublicationError("candidate_invalid", "release must be agent-id:version")
        agent_id, version = args.release.split(":", 1)
        async with session_factory() as session:
            result = await release_status(session, agent_id, version)
        emit(result, args.as_json)


def main() -> None:
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except PublicationError as error:
        print(f"{error.code}: {error.detail}".rstrip(), file=sys.stderr)
        raise SystemExit(EXIT_CODES.get(error.code, EXIT_CODES["internal_failure"])) from None
    except (ConnectionError, OSError, SQLAlchemyError) as error:
        print(f"dependency_failure: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(EXIT_CODES["dependency_failure"]) from None


if __name__ == "__main__":
    main()
