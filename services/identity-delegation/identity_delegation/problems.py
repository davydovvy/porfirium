from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(frozen=True, slots=True)
class DelegationProblem(Exception):
    status: int
    code: str
    title: str


def problem_response(request: Request, problem: DelegationProblem) -> JSONResponse:
    try:
        correlation_id = UUID(request.headers.get("X-Correlation-ID", ""))
    except ValueError:
        correlation_id = uuid4()
    content = {
        "type": f"https://porfirium.local/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "code": problem.code,
        "correlation_id": str(correlation_id),
        "retryable": False,
    }
    return JSONResponse(
        status_code=problem.status,
        content=content,
        headers={"X-Correlation-ID": str(correlation_id)},
        media_type="application/problem+json",
    )
