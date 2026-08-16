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


def workflow_id(turn_id: uuid.UUID) -> str:
    return f"porfirium-agent-{turn_id}"
