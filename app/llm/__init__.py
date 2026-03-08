"""LLM provider factory."""

from typing import Any

__all__ = ["get_llm"]


def get_llm(*args: Any, **kwargs: Any) -> Any:
    from app.llm.factory import get_llm as _get_llm

    return _get_llm(*args, **kwargs)
