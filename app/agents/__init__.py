"""Agent components."""

from typing import Any

from app.agents.router_agent import RouterDecision, route_message

__all__ = [
    "AGENT_CONFIGS",
    "AnalysisAgent",
    "ErrorAgent",
    "GuardrailAgent",
    "GuardrailsAgent",
    "RouterDecision",
    "SQLAgent",
    "VizAgent",
    "route_message",
]


def __getattr__(name: str) -> Any:
    if name == "AGENT_CONFIGS":
        from app.agents.agent_configs import AGENT_CONFIGS

        return AGENT_CONFIGS
    if name == "AnalysisAgent":
        from app.agents.analysis_agent import AnalysisAgent

        return AnalysisAgent
    if name == "ErrorAgent":
        from app.agents.error_agent import ErrorAgent

        return ErrorAgent
    if name == "GuardrailAgent":
        from app.agents.guardrail_agent import GuardrailAgent

        return GuardrailAgent
    if name == "GuardrailsAgent":
        from app.agents.guardrail_agent import GuardrailsAgent

        return GuardrailsAgent
    if name == "SQLAgent":
        from app.agents.sql_agent import SQLAgent

        return SQLAgent
    if name == "VizAgent":
        from app.agents.viz_agent import VizAgent

        return VizAgent
    raise AttributeError(f"module 'app.agents' has no attribute {name!r}")
