"""Pipeline entrypoints."""

from typing import Any

from app.pipeline.execute_sql import execute_sql

__all__ = [
    "build_text2sql_graph",
    "execute_sql",
    "get_graph_app",
    "invoke_graph_pipeline",
    "run_data_pipeline",
    "run_reviewed_sql",
]


def run_data_pipeline(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.data_pipeline import run_data_pipeline as _run_data_pipeline

    return _run_data_pipeline(*args, **kwargs)


def build_text2sql_graph(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.langgraph_flow import build_text2sql_graph as _build_text2sql_graph

    return _build_text2sql_graph(*args, **kwargs)


def get_graph_app(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.langgraph_flow import get_graph_app as _get_graph_app

    return _get_graph_app(*args, **kwargs)


def invoke_graph_pipeline(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.langgraph_flow import invoke_graph_pipeline as _invoke_graph_pipeline

    return _invoke_graph_pipeline(*args, **kwargs)


def run_reviewed_sql(*args: Any, **kwargs: Any) -> Any:
    from app.pipeline.expert_review import run_reviewed_sql as _run_reviewed_sql

    return _run_reviewed_sql(*args, **kwargs)
