"""Pipeline entrypoints."""

from typing import Any

from app.pipeline.execute_sql import execute_sql

__all__ = ["build_text2sql_graph", "execute_sql", "run_data_pipeline"]


def run_data_pipeline(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.data_pipeline import run_data_pipeline as _run_data_pipeline

    return _run_data_pipeline(*args, **kwargs)


def build_text2sql_graph(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.langgraph_flow import build_text2sql_graph as _build_text2sql_graph

    return _build_text2sql_graph(*args, **kwargs)
