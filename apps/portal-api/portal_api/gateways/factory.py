from __future__ import annotations

from ..config import Settings, settings
from .agentgateway import AgentgatewayModelGateway, AgentgatewayToolGateway
from .contracts import ModelGateway, ToolGateway


def create_model_gateway(configuration: Settings = settings) -> ModelGateway:
    return AgentgatewayModelGateway(
        configuration.model_gateway_url,
        timeout_seconds=configuration.llm_timeout_seconds,
        model_alias=configuration.agentgateway_model_alias,
    )


def create_tool_gateway(configuration: Settings = settings) -> ToolGateway:
    return AgentgatewayToolGateway(
        configuration.tool_gateway_url,
        timeout_seconds=configuration.tool_gateway_timeout_seconds,
    )
