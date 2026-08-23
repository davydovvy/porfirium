# ruff: noqa: E501
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from jsonschema import Draft202012Validator
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from .agent import AgentRunWorkflow
from .chat import append_event
from .config import settings
from .db import session_factory
from .gateways import ModelRequest, ToolCall, create_model_gateway, create_tool_gateway
from .gateways.contracts import ToolDefinition
from .models import AgentRunSnapshot, Message, ToolRequest, Turn, now_utc
from .run_contracts import validate_run_snapshot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
model_gateway = create_model_gateway()
tool_gateway = create_tool_gateway()


def tool_rejection_result(reason: str) -> dict[str, object]:
    return {"error": reason, "retryable": True}


def stored_tool_arguments(allowed: bool, arguments: dict[str, object], raw: str) -> dict[str, object]:
    return arguments if allowed else {"rejected": True, "argument_bytes": len(raw.encode())}


async def _contract(session, value: dict) -> tuple[Turn, dict[str, object]]:
    try:
        turn_id = uuid.UUID(str(value["turn_id"]))
        snapshot_id = uuid.UUID(str(value["run_snapshot_id"]))
    except (KeyError, ValueError) as exc:
        raise ApplicationError("agent_run_identifiers_invalid", non_retryable=True) from exc
    turn = await session.get(Turn, turn_id)
    snapshot = await session.get(AgentRunSnapshot, snapshot_id)
    if turn is None or snapshot is None:
        raise ApplicationError("agent_run_snapshot_missing", non_retryable=True)
    if turn.agent_run_snapshot_id != snapshot.id:
        raise ApplicationError("agent_run_snapshot_binding_mismatch", non_retryable=True)
    contract = snapshot.snapshot
    try:
        validate_run_snapshot(contract)
    except ValueError as exc:
        raise ApplicationError(str(exc), non_retryable=True) from exc
    agent = contract["agent"]
    if not isinstance(agent, dict) or str(snapshot.agent_version_id) != agent.get("version_id"):
        raise ApplicationError("agent_run_snapshot_identity_mismatch", non_retryable=True)
    if snapshot.digest != agent.get("digest"):
        raise ApplicationError("agent_run_snapshot_digest_mismatch", non_retryable=True)
    return turn, contract


@activity.defn(name="load_agent_run_plan")
async def load_agent_run_plan(value: dict) -> dict[str, int]:
    async with session_factory() as session:
        _, contract = await _contract(session, value)
    limits = contract["limits"]
    assert isinstance(limits, dict)
    return {
        "contract_version": int(contract["contract_version"]),
        "max_iterations": int(limits["max_iterations"]),
        "max_tool_calls_per_step": int(limits["max_tool_calls_per_step"]),
    }


@activity.defn(name="mark_agent_run_running")
async def mark_agent_run_running(value: dict) -> None:
    async with session_factory() as session:
        turn, _ = await _contract(session, value)
        if turn.state not in {"completed", "cancelled"}:
            turn.state = "running"
            turn.updated_at = now_utc()
            await session.commit()
            identifier = turn.id
        else:
            return
    await append_event(identifier, "agent.status", {"status": "planning", "label": "Planning response"})


def _text(payload: dict[str, object]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    return "".join(
        str(part.get("text", ""))
        for item in payload.get("output", []) if isinstance(item, dict)
        for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
    )


@activity.defn(name="generate_agent_run_step")
async def generate_agent_run_step(value: dict) -> dict[str, object]:
    iteration = int(value["iteration"])
    final_only = value.get("final_only") is True
    async with session_factory() as session:
        turn, contract = await _contract(session, value)
        identifier = turn.id
        history = list((await session.scalars(select(Message).where(Message.conversation_id == turn.conversation_id).order_by(Message.created_at, Message.id))).all())
        completed = list((await session.scalars(select(ToolRequest).where(ToolRequest.turn_id == turn.id, ToolRequest.state.in_(("completed", "denied"))).order_by(ToolRequest.iteration, ToolRequest.created_at))).all())
        model_input: list[dict[str, object]] = [{"role": item.role, "content": item.content} for item in history if item.content]
        for item in completed:
            model_input.extend([
                {"type": "function_call", "call_id": item.tool_call_id, "name": item.external_tool_name, "arguments": json.dumps(item.arguments, separators=(",", ":"))},
                {"type": "function_call_output", "call_id": item.tool_call_id, "output": json.dumps(item.result or tool_rejection_result(item.decision_reason), separators=(",", ":"))},
            ])
        tools = contract["tools"]
        assert isinstance(tools, list)
        definitions = () if final_only else tuple(ToolDefinition(name=str(tool["stable_name"]), description=f"Read-only {tool['tool_name']} operation.", input_schema=tool["definition"]) for tool in tools if isinstance(tool, dict))
        model = contract["model"]
        limits = contract["limits"]
        agent = contract["agent"]
        assert isinstance(model, dict) and isinstance(limits, dict) and isinstance(agent, dict)
        request = ModelRequest(
            model=str(model["model"]), input=model_input, correlation_id=turn.correlation_id,
            instructions=str(contract["instructions"]), max_output_tokens=int(limits["max_output_tokens"]),
            tools=tuple(item.name for item in definitions), tool_definitions=definitions, tool_choice="none" if final_only else "auto",
            metadata={"turn_id": str(turn.id), "snapshot_id": str(value["run_snapshot_id"]), "agent_version": str(agent["version"]), "agent_digest": str(agent["digest"]), "runtime_contract_version": "1", "iteration": str(iteration)},
        )
    await append_event(
        identifier,
        "agent.status",
        {
            "status": "generating" if iteration == 0 else "synthesizing",
            "label": "Preparing final response" if final_only else "Selecting tools" if iteration == 0 else "Synthesizing tool results",
        },
    )
    activity.heartbeat(f"calling-model-{iteration}")
    payload = dict((await model_gateway.respond(request)).payload)
    calls = [{"model_call_id": str(payload.get("id", "unknown")), "tool_call_id": str(item.get("call_id", item.get("id", ""))), "name": str(item.get("name", "")), "arguments": str(item.get("arguments", ""))} for item in payload.get("output", []) if isinstance(item, dict) and item.get("type") == "function_call"]
    if calls:
        return {"tool_calls": calls}
    text = _text(payload)
    if not text:
        raise ApplicationError("model_output_empty", non_retryable=True)
    return {"final": text}


@activity.defn(name="authorize_agent_run_tool")
async def authorize_agent_run_tool(value: dict) -> dict[str, str]:
    call = value.get("call")
    if not isinstance(call, dict):
        raise ApplicationError("tool_call_invalid", non_retryable=True)
    name, raw = str(call.get("name", "")), str(call.get("arguments", ""))
    async with session_factory() as session:
        turn, contract = await _contract(session, value)
        existing = await session.scalar(select(ToolRequest).where(ToolRequest.turn_id == turn.id, ToolRequest.tool_call_id == str(call.get("tool_call_id", ""))))
        if existing:
            return {"request_id": str(existing.id), "decision": existing.decision}
        grant = next((tool for tool in contract["tools"] if isinstance(tool, dict) and tool.get("stable_name") == name), None)
        reason = "allowed"
        arguments: dict[str, object] = {}
        if grant is None:
            reason = "tool_not_granted_to_agent_version"
        elif len(raw.encode()) > int(contract["limits"]["max_tool_argument_bytes"]):
            reason = "tool_arguments_too_large"
        else:
            try:
                parsed = json.loads(raw)
                errors = list(Draft202012Validator(grant["definition"]).iter_errors(parsed))
                if not isinstance(parsed, dict) or errors:
                    reason = "tool_arguments_schema_invalid"
                else:
                    arguments = parsed
            except json.JSONDecodeError:
                reason = "tool_arguments_invalid_json"
        allowed = reason == "allowed"
        agent = contract["agent"]
        request = ToolRequest(turn_id=turn.id, owner_id=turn.owner_id, workflow_id=turn.workflow_id or "unknown", model_call_id=str(call.get("model_call_id", "unknown")), tool_call_id=str(call.get("tool_call_id", "")), iteration=int(value["iteration"]), agent_name=str(agent["id"]), agent_version=str(agent["version"]), policy_version=str(grant["policy_version"]) if grant else "snapshot-v1", server_name=str(grant["server_name"]) if grant else "unknown", tool_name=str(grant["tool_name"]) if grant else "unknown", external_tool_name=name, schema_version=str(grant["schema_version"]) if grant else "unknown", arguments=stored_tool_arguments(allowed, arguments, raw), decision="allowed" if allowed else "denied", decision_reason=reason, state="requested" if allowed else "denied", result=None if allowed else tool_rejection_result(reason), correlation_id=turn.correlation_id, completed_at=None if allowed else now_utc())
        session.add(request)
        await session.commit()
        request_id, identifier = request.id, turn.id
    await append_event(identifier, "tool.requested", {"request_id": str(request_id), "tool": name, "decision": request.decision, "label": f"Requested {name}"})
    if not allowed:
        await append_event(identifier, "tool.completed", {"request_id": str(request_id), "tool": name, "status": "denied", "reason": reason, "label": f"Denied {name}"})
        return {"request_id": str(request_id), "decision": "denied"}
    return {"request_id": str(request_id), "decision": "allowed"}


@activity.defn(name="execute_agent_run_tool")
async def execute_agent_run_tool(value: dict) -> None:
    request_id = uuid.UUID(str(value["request_id"]))
    async with session_factory() as session:
        turn, contract = await _contract(session, value)
        request = await session.get(ToolRequest, request_id)
        if request is None or request.turn_id != turn.id or request.decision != "allowed":
            raise ApplicationError("tool_not_authorized", non_retryable=True)
        if request.state in {"executed", "completed"}:
            return
        emit_started = request.state == "requested"
        request.state, request.started_at = "started", request.started_at or now_utc()
        await session.commit()
        limit = int(contract["limits"]["max_tool_result_bytes"])
        call = ToolCall(call_id=request.tool_call_id, name=request.external_tool_name, arguments=request.arguments, correlation_id=request.correlation_id, max_result_bytes=limit)
        identifier = turn.id
        name = request.external_tool_name
    if emit_started:
        await append_event(identifier, "tool.started", {"request_id": str(request_id), "tool": name, "label": f"Running {name}"})
    result = dict((await tool_gateway.call_tool(call)).payload)
    if len(json.dumps(result, separators=(",", ":")).encode()) > limit:
        raise ApplicationError("tool_result_too_large", non_retryable=True)
    async with session_factory() as session:
        request = await session.get(ToolRequest, request_id)
        if request and request.state != "completed":
            request.state, request.result = "executed", result
            await session.commit()


@activity.defn(name="record_agent_run_tool_result")
async def record_agent_run_tool_result(value: dict) -> None:
    request_id = uuid.UUID(str(value["request_id"]))
    async with session_factory() as session:
        turn, _ = await _contract(session, value)
        request = await session.get(ToolRequest, request_id)
        if request is None or request.turn_id != turn.id:
            raise ApplicationError("tool_audit_missing", non_retryable=True)
        if request.state == "completed":
            return
        if request.state != "executed":
            raise ApplicationError("tool_result_not_executed", non_retryable=True)
        request.state, request.completed_at = "completed", now_utc()
        await session.commit()
        name = request.external_tool_name
    await append_event(turn.id, "tool.completed", {"request_id": str(request_id), "tool": name, "status": "completed", "label": f"Completed {name}"})


@activity.defn(name="complete_agent_run")
async def complete_agent_run(value: dict) -> None:
    content = str(value["content"])
    async with session_factory() as session:
        turn, _ = await _contract(session, value)
        if turn.state == "cancelled":
            return
        message = await session.scalar(select(Message).where(Message.turn_id == turn.id, Message.role == "assistant"))
        if message is None:
            message = Message(conversation_id=turn.conversation_id, turn_id=turn.id, role="assistant", content=content, status="complete")
            session.add(message)
        turn.state, turn.updated_at = "completed", now_utc()
        await session.commit()
        identifier, message_id = turn.id, message.id
    await append_event(identifier, "turn.completed", {"message_id": str(message_id), "content": content})


@activity.defn(name="fail_agent_run")
async def fail_agent_run(value: dict) -> None:
    identifier = uuid.UUID(str(value["turn_id"]))
    async with session_factory() as session:
        turn = await session.get(Turn, identifier)
        if turn is None or turn.state in {"completed", "cancelled"}:
            return
        turn.state, turn.error_code, turn.updated_at = "failed", "agent_execution_failed", now_utc()
        await session.commit()
        correlation_id = turn.correlation_id
    await append_event(identifier, "turn.failed", {"code": "agent_execution_failed", "message": "The durable agent could not complete this run.", "correlation_id": correlation_id})


async def run() -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(client, task_queue=settings.temporal_agent_run_task_queue, workflows=[AgentRunWorkflow], activities=[load_agent_run_plan, mark_agent_run_running, generate_agent_run_step, authorize_agent_run_tool, execute_agent_run_tool, record_agent_run_tool_result, complete_agent_run, fail_agent_run])
    logger.info("Generic agent worker listening task_queue=%s", settings.temporal_agent_run_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run())
