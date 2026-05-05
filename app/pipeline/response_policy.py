from __future__ import annotations

from typing import Any, Sequence

from app.formatters.viz_plotly import describe_result_set
from app.messages import (
    GREETING_RESPONSES,
    OUT_OF_SCOPE_MESSAGE,
    PII_EXPOSURE_REFUSAL,
    VIZ_NO_DATA_MESSAGE,
)

UNSAFE_SQL_REFUSAL_MESSAGE = (
    "I can't help execute or assist with destructive or raw SQL commands. "
    "Ask an analytics question instead."
)


def build_out_of_scope_answer(parsed_intent: str, notes: str = "") -> str:
    intent = (parsed_intent or "").strip()
    if intent == "greeting":
        return notes or GREETING_RESPONSES[0]
    if intent == "unsafe_sql_or_injection":
        return UNSAFE_SQL_REFUSAL_MESSAGE
    if intent == "pii_request":
        return PII_EXPOSURE_REFUSAL
    if intent == "non_data_chat" and notes:
        return notes
    return OUT_OF_SCOPE_MESSAGE


def build_viz_no_data_answer(prior_route: str = "", prior_question: str = "") -> str:
    route = (prior_route or "").strip().upper()
    question = " ".join((prior_question or "").strip().split())
    if route == "CLARIFY":
        if question:
            return (
                'I can\'t plot yet because we still haven\'t produced a result for "{}". '
                "First answer the clarification so I can build the data to visualize."
            ).format(question)
        return (
            "I can't plot yet because we still haven't produced a chartable result. "
            "First answer the clarification so I can build the data to visualize."
        )
    if route in {"CHAT", "OUT_OF_SCOPE", "ERROR", ""}:
        return (
            "I do not have a recent analytical result to plot yet. "
            "Ask a grouped analytics question first, such as top communes by clients in 2024."
        )
    return VIZ_NO_DATA_MESSAGE


def should_use_deterministic_data_summary(columns: Sequence[str], rows: Any) -> bool:
    cols = [str(column) for column in (columns or [])]
    if not rows:
        return True
    if len(cols) <= 2:
        return True
    profile = describe_result_set(cols, rows)
    return profile.get("semantic_type") in {"empty", "scalar", "time_series", "categorical_comparison", "numeric_pair"}


def compose_data_answer(
    *,
    question: str,
    sql: str,
    columns: Sequence[str],
    rows: Any,
    fallback_text: str,
    analysis_agent: Any,
) -> str:
    if should_use_deterministic_data_summary(columns, rows):
        return fallback_text
    return analysis_agent.summarize(
        question=question,
        sql=sql,
        columns=columns,
        rows=rows,
        fallback_text=fallback_text,
    )