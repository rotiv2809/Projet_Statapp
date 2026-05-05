from __future__ import annotations

from typing import Sequence

GREETING_RESPONSES = (
    "Hello. I can help you explore your data. For example: 'How many clients per segment in 2024?'",
    "Hi. Ask me about your clients, transactions, or dossiers. For example: 'Top 10 communes by total amount in 2024'.",
    "Hello. Try a question like: 'Top 10 communes by number of transactions in 2024'.",
)

OUT_OF_SCOPE_MESSAGE = (
    "I can help with analytics questions about clients, transactions, and dossiers. "
    "Please rephrase your question around those topics."
)
CLARIFY_REQUEST_MESSAGE = "Could you clarify your request?"
VIZ_NO_DATA_MESSAGE = (
    "There is no recent chart-ready result in memory. Ask a grouped analytics question first, "
    "such as top communes by clients in 2024."
)
VIZ_UNSUPPORTED_MESSAGE = (
    "I cannot build a chart from that result. Please ask for grouped data, "
    "such as counts by category or values over time."
)
VIZ_FOLLOWUP_MESSAGE = "Here is the visualization for your previous query."
GENERIC_ERROR_MESSAGE = "An error occurred."
DONE_MESSAGE = "Done."
CLARIFICATION_ACK_PREFIX = "Got it! "
NO_RESULTS_MESSAGE = "No results."
PII_EXPOSURE_REFUSAL = "Refused: the query attempts to expose personal data."
PIPELINE_NONE_MESSAGE = "Pipeline returned no result."
FAILED_EXECUTABLE_SQL_MESSAGE = (
    "I could not produce a valid executable SQL query after several repair attempts."
)
PLOT_SUGGESTION = (
    '\n\nI can plot this data for you - just ask '
    '(for example, "plot a bar chart" or "show me a pie chart").'
)


def build_ranking_clarification_message(missing_slots: Sequence[str]) -> str:
    missing = set(missing_slots or [])
    if {"metric", "time_range"}.issubset(missing):
        return (
            "I can rank the communes, but I need two details first: should I rank them by "
            "total amount or by number of transactions, and for which period, for example "
            "2024 or a specific month?"
        )
    if "metric" in missing:
        return (
            "I can rank the communes, but what should I rank them by: total amount, "
            "number of transactions, or another metric?"
        )
    if "time_range" in missing:
        return (
            "I can rank the communes, but for which period should I do it, for example "
            "2024 or a specific month?"
        )
    return "I can look that up, but I need one more detail to answer correctly."


def format_general_results_summary(total_rows: int, preview_count: int) -> str:
    text = "Results: {} rows. Preview: {} rows.".format(total_rows, preview_count)
    if total_rows > preview_count:
        text += " (truncated to {})".format(preview_count)
    return text


def pipeline_error_message(exc: BaseException) -> str:
    return "Pipeline error: {}: {}".format(type(exc).__name__, exc)


def sql_generation_failed_message(exc: BaseException) -> str:
    return "SQL generation failed: {}: {}".format(type(exc).__name__, exc)


def sql_repair_failed_message(exc: BaseException) -> str:
    return "SQL repair failed: {}: {}".format(type(exc).__name__, exc)
