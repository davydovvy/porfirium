from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class CheckpointProblem(Exception):
    status: int
    code: str
    title: str
    retryable: bool = False
    details: dict[str, object] | None = None


def problem_response(request: Request, problem: CheckpointProblem) -> JSONResponse:
    try:
        correlation_id = UUID(request.headers.get("X-Correlation-ID", ""))
    except ValueError:
        correlation_id = uuid4()
    content: dict[str, object] = {
        "type": f"https://porfirium.local/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "code": problem.code,
        "correlation_id": str(correlation_id),
        "retryable": problem.retryable,
    }
    if problem.details:
        content["details"] = problem.details
    headers = {"X-Correlation-ID": str(correlation_id)}
    if problem.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=problem.status,
        content=content,
        headers=headers,
        media_type="application/problem+json",
    )
