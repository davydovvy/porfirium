from __future__ import annotations

from ..config import Settings, settings
from .bifrost import BifrostModelGateway, BifrostToolGateway
from .contracts import GatewayConfigurationError, ModelGateway, ToolGateway


def create_model_gateway(configuration: Settings = settings) -> ModelGateway:
    if configuration.model_gateway_provider != "bifrost":
        raise GatewayConfigurationError(
            f"unsupported_model_gateway_provider:{configuration.model_gateway_provider}"
        )
    return BifrostModelGateway(
        configuration.model_gateway_url,
        timeout_seconds=configuration.llm_timeout_seconds,
        model_prefix=configuration.bifrost_model_prefix,
    )


def create_tool_gateway(configuration: Settings = settings) -> ToolGateway:
    if configuration.tool_gateway_provider != "bifrost":
        raise GatewayConfigurationError(
            f"unsupported_tool_gateway_provider:{configuration.tool_gateway_provider}"
        )
    return BifrostToolGateway(
        configuration.tool_gateway_url,
        timeout_seconds=configuration.tool_gateway_timeout_seconds,
    )
