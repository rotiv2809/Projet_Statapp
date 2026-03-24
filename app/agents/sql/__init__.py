"""SQL generation package."""

from typing import Any

__all__ = ["SQLAgent", "SQL_SYSTEM_PROMPT"]


def __getattr__(name: str) -> Any:
    if name == "SQLAgent":
        from app.agents.sql.agent import SQLAgent

        return SQLAgent
    if name == "SQL_SYSTEM_PROMPT":
        from app.agents.sql.prompt import SQL_SYSTEM_PROMPT

        return SQL_SYSTEM_PROMPT
    raise AttributeError(f"module 'app.agents.sql' has no attribute {name!r}")
