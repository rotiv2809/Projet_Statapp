"""Application package for StatApp."""

from typing import Any

__all__ = ["run_data_pipeline"]


def run_data_pipeline(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.data_pipeline import run_data_pipeline as _run_data_pipeline

    return _run_data_pipeline(*args, **kwargs)
