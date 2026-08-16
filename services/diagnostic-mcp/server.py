from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route


mcp = FastMCP(
    "GenAI Platform Phase 0 Diagnostics",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[
            "diagnostic-mcp:8091",
            "127.0.0.1:8091",
            "localhost:8091",
        ]
    ),
)


@mcp.tool()
def echo(message: str) -> dict[str, str]:
    """Return the supplied text unchanged to validate MCP execution."""
    return {"message": message, "source": "phase0-diagnostic-mcp"}


@mcp.tool()
def platform_info() -> dict[str, object]:
    """Return non-sensitive information about the Phase 0 diagnostic server."""
    return {
        "component": "phase0-diagnostic-mcp",
        "version": "0.1.0",
        "read_only": True,
        "tools": ["echo", "platform_info"],
    }


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "component": "diagnostic-mcp"})


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


application = Starlette(
    routes=[
        Route("/health", health),
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(application, host="0.0.0.0", port=8091)
