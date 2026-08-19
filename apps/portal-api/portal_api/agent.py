import uuid
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn(name="PorfiriumAgentWorkflowV1")
class AgentWorkflowV1:
    @workflow.run
    async def run(self, turn_id: str) -> str:
        try:
            await workflow.execute_activity(
                "mark_agent_running",
                turn_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            # A durable timer provides a visible recovery window without holding a worker thread.
            await workflow.sleep(timedelta(seconds=3))
            response = await workflow.execute_activity(
                "generate_agent_response",
                turn_id,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            await workflow.execute_activity(
                "complete_agent_turn",
                {"turn_id": turn_id, "content": response},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            return response
        except ActivityError:
            await workflow.execute_activity(
                "fail_agent_turn",
                turn_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            raise


@workflow.defn(name="PorfiriumToolAgentWorkflowV2")
class ToolAgentWorkflowV2:
    @workflow.run
    async def run(self, turn_id: str) -> str:
        try:
            await workflow.execute_activity(
                "mark_agent_running",
                turn_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            for iteration in range(4):
                step = await workflow.execute_activity(
                    "generate_agent_step",
                    {"turn_id": turn_id, "iteration": iteration},
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(seconds=15),
                    retry_policy=RetryPolicy(maximum_attempts=5),
                )
                final = step.get("final")
                if isinstance(final, str):
                    await workflow.execute_activity(
                        "complete_agent_turn",
                        {"turn_id": turn_id, "content": final},
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=10),
                    )
                    return final
                calls = step.get("tool_calls", [])
                if not isinstance(calls, list) or not calls:
                    raise ValueError("agent step returned neither final text nor tool calls")
                for call in calls:
                    authorization = await workflow.execute_activity(
                        "authorize_agent_tool",
                        {"turn_id": turn_id, "iteration": iteration, "call": call},
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=10),
                    )
                    # This durable boundary makes worker-restart recovery observable and testable.
                    await workflow.sleep(timedelta(seconds=3))
                    request_id = str(authorization["request_id"])
                    await workflow.execute_activity(
                        "execute_agent_tool",
                        request_id,
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    await workflow.execute_activity(
                        "record_agent_tool_result",
                        request_id,
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=10),
                    )
            raise ValueError("agent iteration limit exceeded")
        except (ActivityError, ValueError):
            await workflow.execute_activity(
                "fail_agent_turn",
                turn_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=10),
            )
            raise


def workflow_id(turn_id: uuid.UUID) -> str:
    return f"porfirium-agent-{turn_id}"
