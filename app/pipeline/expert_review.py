from __future__ import annotations

import logging
import re
from typing import Any, Dict

from app.agents.sql.retrieval import add_example
from app.db.corrections import log_correction
from app.formatters.format_response import format_response_dict, with_plot_suggestion
from app.formatters.viz_plotly import can_visualize, infer_plotly
from app.logging_utils import get_logger, log_event
from app.pipeline.conversation_state import build_conversation_state, build_result_object
from app.pipeline.execute_sql import execute_sql

logger = get_logger(__name__)


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").strip().rstrip(";"))


def run_reviewed_sql(
    *,
    db_path: str,
    question: str,
    generated_sql: str,
    reviewed_sql: str,
    review_user: str = "expert",
) -> Dict[str, Any]:
    sql = (reviewed_sql or "").strip()

    def _finalize(
        payload: Dict[str, Any],
        *,
        level: int,
        event: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        result = dict(payload)
        log_event(
            logger,
            level,
            event,
            db_path=db_path,
            stage=result.get("stage", ""),
            route=result.get("route", ""),
            review_user=review_user,
            **fields,
        )
        return result

    if not sql:
        result = {
            "ok": False,
            "route": "ERROR",
            "stage": "expert_review",
            "sql": sql,
            "message": "Reviewed SQL cannot be empty.",
        }
        return _finalize(
            result,
            level=logging.WARNING,
            event="expert_review.failed",
            error="Reviewed SQL cannot be empty.",
        )

    log_event(
        logger,
        logging.INFO,
        "expert_review.started",
        db_path=db_path,
        question_preview=question[:120],
        review_user=review_user,
    )

    execution = execute_sql(db_path, sql)
    if not execution.get("ok"):
        error = execution.get("error", "Unknown SQL execution error.")
        result = {
            "ok": False,
            "route": "ERROR",
            "stage": "expert_review",
            "sql": sql,
            "error": error,
            "message": "Expert SQL review failed: {}".format(error),
        }
        return _finalize(result, level=logging.WARNING, event="expert_review.failed", sql=sql, error=error)

    columns = execution.get("columns", [])
    rows = execution.get("rows", [])
    formatted = format_response_dict(columns, rows)
    viz = infer_plotly(question, columns, rows)
    result_object = build_result_object(
        columns,
        rows,
        sql=sql,
        question=question,
        summary_text=formatted["text"],
        context_filters={},
        current_grouping=[],
        time_reference={},
        entity_focus="",
    )

    correction_applied = _normalize_sql(generated_sql) != _normalize_sql(sql)
    saved_correction = False
    save_error = ""

    if correction_applied:
        try:
            log_correction(
                db_path=db_path,
                question=question,
                generated_sql=generated_sql,
                corrected_sql=sql,
                user=review_user or "expert",
            )
            saved_correction = True
            # Feed the corrected pair into the RAG example store so future
            # SQL generation retrieves it via TF-IDF similarity, not just
            # the exact/fuzzy string path in fetch_similar_correction.
            try:
                add_example(question, sql)
            except Exception:
                pass
        except Exception as exc:
            save_error = str(exc)
            log_event(
                logger,
                logging.WARNING,
                "expert_review.correction_log_failed",
                db_path=db_path,
                sql=sql,
                error=save_error,
                review_user=review_user,
            )

    if correction_applied and saved_correction:
        prefix = "Executed expert-corrected SQL and saved the correction."
    elif correction_applied:
        prefix = "Executed expert-corrected SQL."
    else:
        prefix = "Executed reviewed SQL."

    answer_body = formatted["text"]
    if can_visualize(columns, rows):
        answer_body = with_plot_suggestion(answer_body)
    answer_text = "{}\n\n{}".format(prefix, answer_body)
    conversation_state = build_conversation_state(
        question=question,
        route="DATA",
        sql=sql,
        result_object=result_object,
        metric="",
        dimensions=[],
        time_range={},
        filters={},
        sort_by="",
        sort_direction="",
        aggregation_intent="",
        last_user_intent="expert_review",
        answer_text=answer_text,
    )
    result = {
        "ok": True,
        "route": "DATA",
        "stage": "expert_review",
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "answer_text": answer_text,
        "answer_table": formatted["table"],
        "preview_rows": formatted["preview_rows"],
        "preview_row_count": formatted["preview_row_count"],
        "total_rows": formatted["total_rows"],
        "viz": viz,
        "result_object": result_object,
        "conversation_state": conversation_state,
        "correction_applied": correction_applied,
        "saved_correction": saved_correction,
        "review_user": review_user or "expert",
    }
    if save_error:
        result["save_error"] = save_error
    return _finalize(
        result,
        level=logging.INFO,
        event="expert_review.completed",
        sql=sql,
        row_count=len(rows),
        correction_applied=correction_applied,
        saved_correction=saved_correction,
    )
