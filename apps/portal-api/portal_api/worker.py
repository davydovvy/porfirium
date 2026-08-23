import asyncio
import json
import logging
import uuid

from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from .agent import AgentWorkflowV1, ToolAgentWorkflowV2
from .chat import append_event
from .config import settings
from .db import session_factory
from .gateways import ModelRequest, ToolCall, create_model_gateway, create_tool_gateway
from .gateways.contracts import GatewayProtocolError
from .models import AgentRunSnapshot, Message, ToolRequest, Turn, now_utc
from .observability import record_observation
from .tool_policy import (
    POLICY_VERSION,
    allowed_tool_definitions,
    allowed_tool_names,
    validate_tool_call,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
MAX_TOOL_CALLS_PER_STEP = 2
MAX_TOOL_RESULT_BYTES = 32_768
model_gateway = create_model_gateway()
tool_gateway = create_tool_gateway()


async def _run_contract(session, turn: Turn) -> tuple[dict[str, object], set[str]]:
    snapshot = await session.get(AgentRunSnapshot, turn.agent_run_snapshot_id)
    if snapshot is None:
        raise ApplicationError("agent_run_snapshot_missing", non_retryable=True)
    contract = snapshot.snapshot
    manifest = contract.get("manifest")
    tools = contract.get("tools")
    if not isinstance(manifest, dict) or not isinstance(tools, list):
        raise ApplicationError("agent_run_snapshot_invalid", non_retryable=True)
    granted = {
        str(tool["stable_name"])
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("stable_name"), str)
    }
    declared = manifest.get("tools")
    if not isinstance(declared, list) or set(map(str, declared)) != granted:
        raise ApplicationError("agent_run_snapshot_grants_mismatch", non_retryable=True)
    return contract, granted


@activity.defn(name="mark_agent_running")
async def mark_agent_running(turn_id: str) -> None:
    identifier = uuid.UUID(turn_id)
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state in {"completed", "cancelled"}:
            return
        turn.state = "running"
        turn.updated_at = now_utc()
        await session.commit()
    await append_event(
        identifier, "agent.status", {"status": "planning", "label": "Planning response"}
    )


@activity.defn(name="generate_agent_response")
async def generate_agent_response(turn_id: str) -> str:
    identifier = uuid.UUID(turn_id)
    await append_event(
        identifier, "agent.status", {"status": "generating", "label": "Generating response"}
    )
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None:
            raise ValueError("Turn no longer exists")
        history = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == turn.conversation_id)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )
        model_request = ModelRequest(
            model=settings.llm_model,
            input=[
                {"role": item.role, "content": item.content} for item in history if item.content
            ],
            correlation_id=turn.correlation_id,
            instructions=(
                "You are Porfirium's durable agent. Answer the user clearly and completely. "
                "Do not claim to use tools; tools are introduced in a later phase."
            ),
            max_output_tokens=settings.llm_max_output_tokens,
            tool_choice="none",
            metadata={
                "conversation_id": str(turn.conversation_id),
                "turn_id": str(turn.id),
                "user_id": str(turn.owner_id),
                "correlation_id": turn.correlation_id,
                "execution": "temporal-agent-v1",
            },
        )
        correlation_id = turn.correlation_id
    activity.heartbeat("calling-model")
    payload = dict((await model_gateway.respond(model_request)).payload)
    activity.heartbeat("model-complete")
    if any(item.get("type") == "function_call" for item in payload.get("output", [])):
        logger.warning(
            "Rejected unexpected Phase 3 tool call correlation_id=%s turn_id=%s",
            correlation_id,
            identifier,
        )
        return (
            "Tools are not available in Agent mode yet. Phase 3 provides durable no-tool "
            "responses; the platform information and MTG tools arrive in Phase 4."
        )
    text = payload.get("output_text")
    if not text:
        text = "".join(
            str(part.get("text", ""))
            for item in payload.get("output", [])
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
    if not text:
        raise ValueError("Model returned no output text")
    return str(text)


def _response_text(payload: dict[str, object]) -> str:
    direct = payload.get("output_text")
    if direct:
        return str(direct)
    return "".join(
        str(part.get("text", ""))
        for item in payload.get("output", [])
        if isinstance(item, dict)
        for part in item.get("content", [])
        if isinstance(part, dict) and part.get("type") == "output_text"
    )


@activity.defn(name="generate_agent_step")
async def generate_agent_step(value: dict) -> dict:
    identifier = uuid.UUID(str(value["turn_id"]))
    iteration = int(value["iteration"])
    await append_event(
        identifier,
        "agent.status",
        {
            "status": "generating" if iteration == 0 else "synthesizing",
            "label": "Selecting tools" if iteration == 0 else "Synthesizing tool results",
        },
    )
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None:
            raise ApplicationError("turn_not_found", non_retryable=True)
        contract, granted_tools = await _run_contract(session, turn)
        manifest = contract["manifest"]
        assert isinstance(manifest, dict)
        history = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == turn.conversation_id)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )
        completed_tools = list(
            (
                await session.scalars(
                    select(ToolRequest)
                    .where(
                        ToolRequest.turn_id == identifier,
                        ToolRequest.decision == "allowed",
                        ToolRequest.state == "completed",
                    )
                    .order_by(ToolRequest.iteration, ToolRequest.created_at)
                )
            ).all()
        )
        model_input: list[dict[str, object]] = [
            {"role": item.role, "content": item.content} for item in history if item.content
        ]
        for tool in completed_tools:
            model_input.extend(
                [
                    {
                        "type": "function_call",
                        "call_id": tool.tool_call_id,
                        "name": tool.external_tool_name,
                        "arguments": json.dumps(tool.arguments, separators=(",", ":")),
                    },
                    {
                        "type": "function_call_output",
                        "call_id": tool.tool_call_id,
                        "output": json.dumps(tool.result, separators=(",", ":")),
                    },
                ]
            )
        model_request = ModelRequest(
            model=settings.llm_model,
            input=model_input,
            correlation_id=turn.correlation_id,
            instructions=str(manifest["instructions"]),
            max_output_tokens=settings.llm_max_output_tokens,
            tools=allowed_tool_names(granted_tools),
            tool_definitions=allowed_tool_definitions(granted_tools),
            tool_choice="auto",
            metadata={
                "conversation_id": str(turn.conversation_id),
                "turn_id": str(turn.id),
                "user_id": str(turn.owner_id),
                "correlation_id": turn.correlation_id,
                "execution": "temporal-tool-agent-v2",
                "iteration": str(iteration),
                "policy_version": POLICY_VERSION,
                "agent_version_id": str(contract["agent_version_id"]),
                "agent_digest": str(contract["digest"]),
            },
        )
        correlation_id = turn.correlation_id
    activity.heartbeat(f"calling-model-{iteration}")
    payload = dict((await model_gateway.respond(model_request)).payload)
    activity.heartbeat(f"model-complete-{iteration}")
    calls = [
        {
            "model_call_id": str(payload.get("id", "unknown")),
            "tool_call_id": str(item.get("call_id", item.get("id", ""))),
            "name": str(item.get("name", "")),
            "arguments": str(item.get("arguments", "")),
        }
        for item in payload.get("output", [])
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    record_observation(
        trace_id=correlation_id,
        name=f"agent.model.iteration.{iteration}",
        as_type="generation",
        input={"iteration": iteration, "available_tools": allowed_tool_names(granted_tools)},
        output={
            "response_id": str(payload.get("id", "unknown")),
            "kind": "tool_calls" if calls else "final_answer",
            "tool_call_count": len(calls),
        },
        metadata={
            "turn_id": str(identifier),
            "iteration": iteration,
            "policy_version": POLICY_VERSION,
            "execution": "temporal-tool-agent-v2",
            "agent_digest": str(contract["digest"]),
        },
        model=settings.llm_model,
    )
    if calls:
        if len(calls) > MAX_TOOL_CALLS_PER_STEP or any(not call["tool_call_id"] for call in calls):
            raise ApplicationError("tool_call_limit_exceeded", non_retryable=True)
        return {"tool_calls": calls}
    text = _response_text(payload)
    if not text:
        raise ApplicationError("model_returned_no_output", non_retryable=True)
    return {"final": text}


@activity.defn(name="authorize_agent_tool")
async def authorize_agent_tool(value: dict) -> dict:
    identifier = uuid.UUID(str(value["turn_id"]))
    iteration = int(value["iteration"])
    call = value["call"]
    if not isinstance(call, dict):
        raise ApplicationError("tool_call_malformed", non_retryable=True)
    name = str(call.get("name", ""))
    raw_arguments = str(call.get("arguments", ""))
    tool_call_id = str(call.get("tool_call_id", ""))
    model_call_id = str(call.get("model_call_id", "unknown"))
    decision = "allowed"
    reason = "policy_allowlisted_read_only"
    try:
        policy, arguments = validate_tool_call(name, raw_arguments)
    except ValueError as exc:
        decision = "denied"
        reason = str(exc)
        server_name, _, tool_name = name.partition("-")
        policy = None
        arguments = {"raw_arguments_rejected": True}
    async with session_factory() as session:
        existing = await session.scalar(
            select(ToolRequest).where(
                ToolRequest.turn_id == identifier, ToolRequest.tool_call_id == tool_call_id
            )
        )
        if existing:
            if existing.decision == "denied":
                raise ApplicationError(existing.decision_reason, non_retryable=True)
            return {"request_id": str(existing.id), "decision": existing.decision}
        turn = await session.get(Turn, identifier)
        if turn is None:
            raise ApplicationError("turn_not_found", non_retryable=True)
        contract, granted_tools = await _run_contract(session, turn)
        if name not in granted_tools:
            decision = "denied"
            reason = "tool_not_granted_to_agent_version"
            policy = None
            arguments = {"raw_arguments_rejected": True}
        manifest = contract["manifest"]
        assert isinstance(manifest, dict)
        agent_manifest = manifest["agent"]
        assert isinstance(agent_manifest, dict)
        request = existing or ToolRequest(
            turn_id=identifier,
            owner_id=turn.owner_id,
            workflow_id=turn.workflow_id or "unknown",
            model_call_id=model_call_id,
            tool_call_id=tool_call_id,
            iteration=iteration,
            agent_name=str(agent_manifest["id"]),
            agent_version=str(agent_manifest["version"]),
            policy_version=POLICY_VERSION,
            server_name=policy.server_name if policy else server_name,
            tool_name=policy.tool_name if policy else tool_name,
            external_tool_name=name,
            schema_version=policy.schema_version if policy else "unknown",
            arguments=arguments,
            decision=decision,
            decision_reason=reason,
            state="requested" if decision == "allowed" else "denied",
            correlation_id=turn.correlation_id,
        )
        if existing is None:
            session.add(request)
        if decision == "denied":
            request.completed_at = now_utc()
        await session.commit()
        request_id = request.id
    await append_event(
        identifier,
        "tool.requested",
        {
            "request_id": str(request_id),
            "tool": name,
            "decision": decision,
            "label": f"Requested {name}",
        },
    )
    if decision == "denied":
        await append_event(
            identifier,
            "tool.completed",
            {
                "request_id": str(request_id),
                "tool": name,
                "status": "denied",
                "reason": reason,
                "label": f"Denied {name}",
            },
        )
        raise ApplicationError(reason, non_retryable=True)
    return {"request_id": str(request_id), "decision": decision}


@activity.defn(name="execute_agent_tool")
async def execute_agent_tool(request_id: str) -> None:
    request_uuid = uuid.UUID(request_id)
    async with session_factory() as session:
        request = await session.get(ToolRequest, request_uuid)
        if request is None:
            raise ApplicationError("tool_audit_missing", non_retryable=True)
        if request.decision != "allowed":
            raise ApplicationError("tool_not_authorized", non_retryable=True)
        if request.state in {"executed", "completed"}:
            return
        if request.state not in {"requested", "started", "failed"}:
            raise ApplicationError("tool_state_invalid", non_retryable=True)
        emit_started = request.state == "requested"
        request.state = "started"
        request.started_at = request.started_at or now_utc()
        request.completed_at = None
        request.error_code = None
        identifier = request.turn_id
        name = request.external_tool_name
        tool_call_id = request.tool_call_id
        raw_arguments = json.dumps(request.arguments, separators=(",", ":"))
        correlation_id = request.correlation_id
        await session.commit()
    if emit_started:
        await append_event(
            identifier,
            "tool.started",
            {"request_id": request_id, "tool": name, "label": f"Running {name}"},
        )
    try:
        result = dict(
            (
                await tool_gateway.call_tool(
                    ToolCall(
                        call_id=tool_call_id,
                        name=name,
                        arguments=json.loads(raw_arguments),
                        correlation_id=correlation_id,
                        max_result_bytes=MAX_TOOL_RESULT_BYTES,
                    )
                )
            ).payload
        )
    except Exception as exc:
        async with session_factory() as session:
            request = await session.get(ToolRequest, request_uuid)
            if request:
                request.state = "failed"
                request.error_code = (
                    str(exc) if isinstance(exc, ApplicationError) else "tool_execution_failed"
                )
                request.completed_at = now_utc()
                await session.commit()
        if isinstance(exc, GatewayProtocolError) and str(exc) == "tool_result_too_large":
            raise ApplicationError("tool_result_too_large", non_retryable=True) from exc
        if isinstance(exc, ApplicationError):
            raise
        raise ApplicationError("tool_execution_failed") from exc
    async with session_factory() as session:
        request = await session.get(ToolRequest, request_uuid)
        if request:
            request.state = "executed"
            request.result = result
            await session.commit()
    record_observation(
        trace_id=correlation_id,
        name=f"agent.tool.{name}",
        as_type="tool",
        input={"request_id": request_id, "arguments": json.loads(raw_arguments)},
        output={"request_id": request_id, "result": result},
        metadata={
            "turn_id": str(identifier),
            "request_id": request_id,
            "tool_call_id": tool_call_id,
            "external_tool_name": name,
            "status": "executed",
        },
    )


@activity.defn(name="record_agent_tool_result")
async def record_agent_tool_result(request_id: str) -> None:
    request_uuid = uuid.UUID(request_id)
    async with session_factory() as session:
        request = await session.get(ToolRequest, request_uuid)
        if request is None:
            raise ApplicationError("tool_audit_missing", non_retryable=True)
        if request.state == "completed":
            return
        if request.state != "executed" or request.result is None:
            raise ApplicationError("tool_result_not_executed", non_retryable=True)
        request.state = "completed"
        request.completed_at = now_utc()
        identifier = request.turn_id
        name = request.external_tool_name
        await session.commit()
    await append_event(
        identifier,
        "tool.completed",
        {
            "request_id": request_id,
            "tool": name,
            "status": "completed",
            "label": f"Completed {name}",
        },
    )


@activity.defn(name="complete_agent_turn")
async def complete_agent_turn(value: dict[str, str]) -> None:
    identifier = uuid.UUID(value["turn_id"])
    content = value["content"]
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state == "cancelled":
            return
        message = await session.scalar(
            select(Message).where(Message.turn_id == identifier, Message.role == "assistant")
        )
        if message is None:
            message = Message(
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                role="assistant",
                content=content,
                status="complete",
            )
            session.add(message)
        else:
            message.content = content
            message.status = "complete"
        turn.state = "completed"
        turn.updated_at = now_utc()
        await session.commit()
        message_id = message.id
    await append_event(
        identifier, "agent.status", {"status": "completed", "label": "Response complete"}
    )
    await append_event(
        identifier, "turn.completed", {"message_id": str(message_id), "content": content}
    )


@activity.defn(name="fail_agent_turn")
async def fail_agent_turn(turn_id: str) -> None:
    identifier = uuid.UUID(turn_id)
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state in {"completed", "cancelled"}:
            return
        turn.state = "failed"
        turn.error_code = "agent_execution_failed"
        turn.updated_at = now_utc()
        await session.commit()
        correlation_id = turn.correlation_id
    await append_event(
        identifier,
        "turn.failed",
        {
            "code": "agent_execution_failed",
            "message": "The durable agent could not complete this run.",
            "correlation_id": correlation_id,
        },
    )


async def run() -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentWorkflowV1, ToolAgentWorkflowV2],
        activities=[
            mark_agent_running,
            generate_agent_response,
            generate_agent_step,
            authorize_agent_tool,
            execute_agent_tool,
            record_agent_tool_result,
            complete_agent_turn,
            fail_agent_turn,
        ],
    )
    logger.info("Agent worker listening task_queue=%s", settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
