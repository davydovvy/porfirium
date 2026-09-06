from __future__ import annotations

from dataclasses import dataclass

from identity_delegation.problems import DelegationProblem


@dataclass(frozen=True, slots=True)
class RunGrant:
    run_id: str
    attempt_id: str
    lease_epoch: int
    models: frozenset[str]
    tools: frozenset[str]
    cancelled: bool = False


def authorize_model(run: RunGrant, model: str) -> None:
    if run.cancelled:
        raise DelegationProblem(409, "run_cancelled", "Run no longer accepts gateway work")
    if model not in run.models:
        raise DelegationProblem(403, "model_forbidden", "Model is not granted to this run")


def authorize_tool(run: RunGrant, tool: str, delegated_scopes: frozenset[str]) -> None:
    if run.cancelled:
        raise DelegationProblem(409, "run_cancelled", "Run no longer accepts gateway work")
    if tool not in run.tools:
        raise DelegationProblem(403, "tool_grant_missing", "Tool is not granted to this run")
    if f"tool:{tool}" not in delegated_scopes:
        raise DelegationProblem(403, "delegated_scope_missing", "User did not delegate this tool")
