from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

SERVER_NAME = "demo-time-mcp"
SERVER_VERSION = "1.0.0"

mcp = FastMCP(
    "Porfirium Demo Time",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "demo-time-mcp:8092",
            "demo-time-mcp",
            "127.0.0.1:8092",
            "127.0.0.1:8089",
            "127.0.0.1",
            "agentgateway:8090",
            "localhost:8092",
            "localhost",
        ]
    ),
)


def _zone(name: str) -> ZoneInfo:
    if not name or len(name) > 128:
        raise ValueError("timezone must be a non-empty IANA timezone name")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown IANA timezone: {name}") from exc


def _result(value: datetime, timezone: str) -> dict[str, object]:
    offset = value.utcoffset()
    return {
        "timestamp": value.isoformat(timespec="seconds"),
        "timezone": timezone,
        "utc_offset_seconds": int(offset.total_seconds()) if offset is not None else 0,
        "is_dst": bool(value.dst()),
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
    }


def current_time(timezone: str, *, now: datetime | None = None) -> dict[str, object]:
    zone = _zone(timezone)
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("internal current-time value must include an offset")
    return _result(instant.astimezone(zone), zone.key)


def _localize_strict(value: datetime, zone: ZoneInfo) -> datetime:
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip == value and all(
            existing.utcoffset() != candidate.utcoffset() for existing in candidates
        ):
            candidates.append(candidate)
    if not candidates:
        raise ValueError("timestamp is not a valid local time in from_timezone")
    if len(candidates) > 1:
        raise ValueError("timestamp is ambiguous in from_timezone; include an explicit UTC offset")
    return candidates[0]


def convert_timestamp(timestamp: str, from_timezone: str, to_timezone: str) -> dict[str, object]:
    if not timestamp or len(timestamp) > 64:
        raise ValueError("timestamp must be a bounded ISO 8601 value")
    source_zone = _zone(from_timezone)
    target_zone = _zone(to_timezone)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO 8601") from exc
    if parsed.tzinfo is None:
        source = _localize_strict(parsed, source_zone)
    else:
        source = parsed.astimezone(source_zone)
    result = _result(source.astimezone(target_zone), target_zone.key)
    result["source_timestamp"] = source.isoformat(timespec="seconds")
    result["source_timezone"] = source_zone.key
    return result


@mcp.tool()
def get_current_time(timezone: str) -> dict[str, object]:
    """Return the current time in an IANA timezone such as Europe/Moscow."""
    return current_time(timezone)


@mcp.tool()
def convert_time(timestamp: str, from_timezone: str, to_timezone: str) -> dict[str, object]:
    """Convert an ISO 8601 timestamp between two IANA timezones."""
    return convert_timestamp(timestamp, from_timezone, to_timezone)


async def health(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "component": SERVER_NAME,
            "version": SERVER_VERSION,
            "read_only": True,
            "tools": ["get_current_time", "convert_time"],
        }
    )


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


application = Starlette(
    routes=[Route("/health", health), Mount("/mcp", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(application, host="0.0.0.0", port=8092)
