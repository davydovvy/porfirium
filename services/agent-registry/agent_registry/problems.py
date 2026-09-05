from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class RegistryProblem(Exception):
    status: int
    code: str
    title: str
    retryable: bool = False
    details: dict[str, object] | None = None


def correlation_id(request: Request) -> UUID:
    candidate = request.headers.get("X-Correlation-ID")
    if candidate is not None:
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def problem_response(request: Request, problem: RegistryProblem) -> JSONResponse:
    content: dict[str, object] = {
        "type": f"https://porfirium.local/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "code": problem.code,
        "correlation_id": str(correlation_id(request)),
        "retryable": problem.retryable,
    }
    if problem.details:
        content["details"] = problem.details
    headers = {"X-Correlation-ID": str(content["correlation_id"])}
    if problem.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=problem.status,
        content=content,
        media_type="application/problem+json",
        headers=headers,
    )
