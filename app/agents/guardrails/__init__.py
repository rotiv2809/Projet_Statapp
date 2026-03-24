"""Guardrails package for gating, routing, and user-input safety."""

from typing import Any

__all__ = [
    "FORBIDDEN_INPUT_PATTERNS",
    "GatekeeperResult",
    "GuardrailAgent",
    "GuardrailsAgent",
    "PII_PATTERN",
    "Route",
    "RouterDecision",
    "SQL_LIKE_START",
    "TimeRange",
    "gatekeep",
    "is_unsafe_user_input",
    "route_message",
]


def __getattr__(name: str) -> Any:
    if name in {"FORBIDDEN_INPUT_PATTERNS", "PII_PATTERN", "SQL_LIKE_START", "gatekeep", "is_unsafe_user_input"}:
        from app.agents.guardrails.gatekeeper import (
            FORBIDDEN_INPUT_PATTERNS,
            PII_PATTERN,
            SQL_LIKE_START,
            gatekeep,
            is_unsafe_user_input,
        )

        mapping = {
            "FORBIDDEN_INPUT_PATTERNS": FORBIDDEN_INPUT_PATTERNS,
            "PII_PATTERN": PII_PATTERN,
            "SQL_LIKE_START": SQL_LIKE_START,
            "gatekeep": gatekeep,
            "is_unsafe_user_input": is_unsafe_user_input,
        }
        return mapping[name]
    if name in {"GatekeeperResult", "TimeRange"}:
        from app.agents.guardrails.schemas import GatekeeperResult, TimeRange

        mapping = {
            "GatekeeperResult": GatekeeperResult,
            "TimeRange": TimeRange,
        }
        return mapping[name]
    if name in {"Route", "RouterDecision", "route_message"}:
        from app.agents.guardrails.router import Route, RouterDecision, route_message

        mapping = {
            "Route": Route,
            "RouterDecision": RouterDecision,
            "route_message": route_message,
        }
        return mapping[name]
    if name in {"GuardrailsAgent", "GuardrailAgent"}:
        from app.agents.guardrails.agent import GuardrailAgent, GuardrailsAgent

        mapping = {
            "GuardrailsAgent": GuardrailsAgent,
            "GuardrailAgent": GuardrailAgent,
        }
        return mapping[name]
    raise AttributeError(f"module 'app.agents.guardrails' has no attribute {name!r}")
