from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class ConversationProblem(Exception):
    status: int
    code: str
    detail: str


def problem_response(request: Request, error: ConversationProblem) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        media_type="application/problem+json",
        content={
            "type": f"urn:porfirium:problem:{error.code}",
            "title": error.code.replace("_", " ").title(),
            "status": error.status,
            "detail": error.detail,
            "instance": request.url.path,
            "code": error.code,
        },
    )
