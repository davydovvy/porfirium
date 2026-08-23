from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TypedDict

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError


class AgentRunInput(TypedDict):
    turn_id: str
    run_snapshot_id: str


def _activity_options(seconds: int = 30) -> dict[str, object]:
    return {
        "start_to_close_timeout": timedelta(seconds=seconds),
        "retry_policy": RetryPolicy(maximum_attempts=5),
    }


@workflow.defn(name="AgentRunWorkflow")
class AgentRunWorkflow:
    """Version-neutral orchestration; all behavior comes from the accepted snapshot."""

    @workflow.run
    async def run(self, value: AgentRunInput) -> str:
        turn_id = value["turn_id"]
        snapshot_id = value["run_snapshot_id"]
        try:
            plan = await workflow.execute_activity(
                "load_agent_run_plan", value, **_activity_options()
            )
            await workflow.execute_activity("mark_agent_run_running", value, **_activity_options())
            for iteration in range(int(plan["max_iterations"])):
                step = await workflow.execute_activity(
                    "generate_agent_run_step",
                    {**value, "iteration": iteration},
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=15),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )
                final = step.get("final")
                if isinstance(final, str) and final:
                    await workflow.execute_activity(
                        "complete_agent_run", {**value, "content": final}, **_activity_options()
                    )
                    return final
                calls = step.get("tool_calls")
                if not isinstance(calls, list) or not calls:
                    raise ApplicationError("agent_step_invalid", non_retryable=True)
                if len(calls) > int(plan["max_tool_calls_per_step"]):
                    raise ApplicationError("agent_tool_call_limit_exceeded", non_retryable=True)
                for call in calls:
                    authorization = await workflow.execute_activity(
                        "authorize_agent_run_tool",
                        {**value, "iteration": iteration, "call": call},
                        **_activity_options(),
                    )
                    request_id = str(authorization["request_id"])
                    await workflow.execute_activity(
                        "execute_agent_run_tool",
                        {**value, "request_id": request_id},
                        **_activity_options(),
                    )
                    await workflow.execute_activity(
                        "record_agent_run_tool_result",
                        {**value, "request_id": request_id},
                        **_activity_options(),
                    )
            raise ApplicationError("agent_iteration_limit_exceeded", non_retryable=True)
        except (ActivityError, ApplicationError):
            await workflow.execute_activity(
                "fail_agent_run",
                {"turn_id": turn_id, "run_snapshot_id": snapshot_id},
                **_activity_options(),
            )
            raise


def workflow_id(turn_id: uuid.UUID) -> str:
    return f"porfirium-agent-{turn_id}"
