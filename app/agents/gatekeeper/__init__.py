"""Gatekeeper layer for scope and safety checks."""

from typing import Any

__all__ = ["GatekeeperResult", "TimeRange", "gatekeep", "is_unsafe_user_input"]


def gatekeep(*args: Any, **kwargs: Any) -> Any:
    from app.agents.gatekeeper.gatekeeper import gatekeep as _gatekeep

    return _gatekeep(*args, **kwargs)


def is_unsafe_user_input(*args: Any, **kwargs: Any) -> Any:
    from app.agents.gatekeeper.gatekeeper import is_unsafe_user_input as _is_unsafe_user_input

    return _is_unsafe_user_input(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name in {"GatekeeperResult", "TimeRange"}:
        from app.agents.gatekeeper.schemas import GatekeeperResult, TimeRange

        mapping = {
            "GatekeeperResult": GatekeeperResult,
            "TimeRange": TimeRange,
        }
        return mapping[name]
    raise AttributeError(f"module 'app.agents.gatekeeper' has no attribute {name!r}")
