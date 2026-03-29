from __future__ import annotations

import logging
import re
from typing import Any, Dict

from app.db.corrections import log_correction
from app.formatters.format_response import format_response_dict, with_plot_suggestion
from app.formatters.viz_plotly import infer_plotly
from app.logging_utils import get_logger, log_event
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
    if not sql:
        return {
            "ok": False,
            "route": "ERROR",
            "stage": "expert_review",
            "sql": sql,
            "message": "Reviewed SQL cannot be empty.",
        }

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
        log_event(
            logger,
            logging.WARNING,
            "expert_review.failed",
            db_path=db_path,
            sql=sql,
            error=error,
            review_user=review_user,
        )
        return {
            "ok": False,
            "route": "ERROR",
            "stage": "expert_review",
            "sql": sql,
            "error": error,
            "message": "Expert SQL review failed: {}".format(error),
        }

    columns = execution.get("columns", [])
    rows = execution.get("rows", [])
    formatted = format_response_dict(columns, rows)
    viz = infer_plotly(question, columns, rows)

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

    answer_text = "{}\n\n{}".format(prefix, with_plot_suggestion(formatted["text"]))
    log_event(
        logger,
        logging.INFO,
        "expert_review.completed",
        db_path=db_path,
        sql=sql,
        row_count=len(rows),
        correction_applied=correction_applied,
        saved_correction=saved_correction,
        review_user=review_user,
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
        "correction_applied": correction_applied,
        "saved_correction": saved_correction,
        "review_user": review_user or "expert",
    }
    if save_error:
        result["save_error"] = save_error
    return result
