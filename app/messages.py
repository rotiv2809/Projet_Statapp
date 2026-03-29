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
    "I do not have any data to visualize yet. Ask a data question first, then I can plot the results."
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


def build_ranking_clarification_message(parts: Sequence[str]) -> str:
    numbered = "\n".join("{}.".format(i + 1) + " " + part for i, part in enumerate(parts))
    return "I can look that up. I just need a couple of details:\n" + numbered


def format_two_column_preview(shown: int, group_col: str, val_col: str, total_rows: int) -> str:
    lines = ["Top {} ({} -> {}):".format(shown, group_col, val_col)]
    if total_rows > shown:
        lines.append("(showing {}/{})".format(shown, total_rows))
    return "\n".join(lines)


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
