"""Shared agent configuration and utilities."""

from typing import Any

__all__ = ["AGENT_CONFIGS", "AgentConfig"]


def __getattr__(name: str) -> Any:
    if name in {"AGENT_CONFIGS", "AgentConfig"}:
        from app.agents.shared.config import AGENT_CONFIGS, AgentConfig

        mapping = {
            "AGENT_CONFIGS": AGENT_CONFIGS,
            "AgentConfig": AgentConfig,
        }
        return mapping[name]
    raise AttributeError(f"module 'app.agents.shared' has no attribute {name!r}")
