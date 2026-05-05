"""
Synchronous orchestration pipeline used by the app today.

Connection in flow:
- Upstream: called by streamlit_app.py and app/main.py.
- This file: runs guardrails -> sql -> validate/execute -> error-retry -> analysis -> viz.
- Downstream: returns one response dict consumed by UI and CLI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any, Dict, List
from app.db.corrections import fetch_similar_correction
from app.db.sqlite import get_prompt_schema_text

from app.agents.analysis_agent import AnalysisAgent
from app.agents.error_agent import ErrorAgent
from app.agents.guardrails.agent import GuardrailsAgent
from app.agents.sql.agent import SQLAgent
from app.llm.factory import LLMConfigurationError
from app.logging_utils import get_logger, log_event
from app.messages import (
    CLARIFY_REQUEST_MESSAGE,
    FAILED_EXECUTABLE_SQL_MESSAGE,
    GREETING_RESPONSES,
    OUT_OF_SCOPE_MESSAGE,
    sql_generation_failed_message,
    sql_repair_failed_message,
)
from app.safety.sql_validator import validate_sql
from app.pipeline.execute_sql import execute_sql
from app.pipeline.conversation_state import build_conversation_state, build_result_object

from app.formatters.format_response import format_response_dict, with_plot_suggestion
from app.formatters.viz_plotly import can_visualize

MAX_SQL_REPAIR_ATTEMPTS = 3
logger = get_logger(__name__)


@dataclass
class SQLAttemptTrace:
    attempt: int
    stage: str
    sql: str
    error: str = ""


def _get_clarifying_questions(gk: Any) -> List[str]:
    qs = getattr(gk, "clarifying_questions", None) or []
    return list(qs)


def run_data_pipeline(db_path: str, question: str) -> Dict[str, Any]:
    schema_text = get_prompt_schema_text(db_path, question)
    guardrails_agent = GuardrailsAgent()

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
            pipeline="sync",
            db_path=db_path,
            route=result.get("route", ""),
            stage=result.get("stage", ""),
            **fields,
        )
        return result

    try:
        sql_agent = SQLAgent()
        error_agent = ErrorAgent()
        analysis_agent = AnalysisAgent()
    except LLMConfigurationError as exc:
        log_event(
            logger,
            logging.ERROR,
            "llm.configuration_error",
            pipeline="sync",
            db_path=db_path,
            question_preview=question[:120],
            error=str(exc),
        )
        result = {
            "ok": False,
            "route": "ERROR",
            "stage": "setup",
            "message": str(exc),
        }
        return _finalize(result, level=logging.ERROR, event="pipeline.failed", error=str(exc))

    log_event(
        logger,
        logging.INFO,
        "pipeline.started",
        pipeline="sync",
        db_path=db_path,
        question_preview=question[:120],
    )

    # Guardrails / scope check
    gk = guardrails_agent.evaluate(question)
    log_event(
        logger,
        logging.INFO,
        "guardrails.decision",
        pipeline="sync",
        status=gk.status,
        reason=gk.parsed_intent,
        notes=gk.notes,
    )
    if gk.status == "OUT OF SCOPE":
        if gk.parsed_intent == "greeting":
            result = {
                "ok": True,
                "route": "CHAT",
                "stage": "guardrails_agent",
                "status": gk.status,
                "reason": gk.parsed_intent,
                "message": gk.notes or GREETING_RESPONSES[0],
                "notes": gk.notes,
            }
            return _finalize(result, level=logging.INFO, event="pipeline.completed", reason=gk.parsed_intent)
        result = {
            "ok": False,
            "route": "OUT_OF_SCOPE",
            "stage": "guardrails_agent",
            "status": gk.status,
            "reason": gk.parsed_intent,
            "message": OUT_OF_SCOPE_MESSAGE,
            "notes": gk.notes,
        }
        return _finalize(result, level=logging.INFO, event="pipeline.completed", reason=gk.parsed_intent)
    if gk.status == "NEEDS CLARIFICATION":
        clarifying_questions = _get_clarifying_questions(gk)
        result = {
            "ok": False,
            "route": "CLARIFY",
            "stage": "guardrails_agent",
            "status": gk.status,
            "message": clarifying_questions[0] if clarifying_questions else CLARIFY_REQUEST_MESSAGE,
            "clarifying_questions": clarifying_questions,
            "missing_slots": gk.missing_slots,
            "notes": gk.notes,
        }
        return _finalize(result, level=logging.INFO, event="pipeline.completed", reason=gk.parsed_intent)

    attempts: List[SQLAttemptTrace] = []
    max_attempts = 1 + MAX_SQL_REPAIR_ATTEMPTS
    reused_correction = False
    memory_fallback_attempted = False

    def _generate_sql_with_llm() -> str:
        generated_sql = sql_agent.generate_sql(question, schema_text=schema_text)
        log_event(
            logger,
            logging.INFO,
            "sql.generated",
            pipeline="sync",
            sql=generated_sql,
        )
        return generated_sql

    try:
        remembered_sql = fetch_similar_correction(db_path, question)
        if remembered_sql:
            sql = remembered_sql
            reused_correction = True
            sql_source = "expert_memory"
            log_event(
                logger,
                logging.INFO,
                "sql.reused_from_memory",
                pipeline="sync",
                sql=sql,
                question_preview=question[:120],
            )
        else:
            sql = _generate_sql_with_llm()
            sql_source = "llm"
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            "sql.generation_failed",
            pipeline="sync",
            error=str(e),
        )
        result = {
            "ok": False,
            "route": "ERROR",
            "stage": "sql_generation",
            "message": sql_generation_failed_message(e),
        }
        return _finalize(result, level=logging.ERROR, event="pipeline.failed", error=str(e))

    exec_res: Dict[str, Any] | None = None
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        is_ok, reason = validate_sql(sql)
        if not is_ok:
            last_error = f"SQL validation failed: {reason}"
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="validation", sql=sql, error=last_error))
            log_event(
                logger,
                logging.WARNING,
                "sql.validation_failed",
                pipeline="sync",
                attempt=attempt,
                sql=sql,
                error=last_error,
            )
            if reused_correction and not memory_fallback_attempted:
                try:
                    sql = _generate_sql_with_llm()
                    sql_source = "llm"
                    memory_fallback_attempted = True
                    log_event(
                        logger,
                        logging.INFO,
                        "sql.memory_fallback_to_llm",
                        pipeline="sync",
                        failed_memory_sql=attempts[-1].sql,
                        error=last_error,
                    )
                    continue
                except Exception as e:
                    log_event(
                        logger,
                        logging.ERROR,
                        "sql.generation_failed_after_memory_fallback",
                        pipeline="sync",
                        error=str(e),
                    )
                    result = {
                        "ok": False,
                        "route": "ERROR",
                        "stage": "sql_generation",
                        "message": sql_generation_failed_message(e),
                    }
                    return _finalize(result, level=logging.ERROR, event="pipeline.failed", error=str(e))
        else:
            candidate = execute_sql(db_path, sql)
            if candidate.get("ok"):
                exec_res = candidate
                attempts.append(SQLAttemptTrace(attempt=attempt, stage="execution", sql=sql))
                log_event(
                    logger,
                    logging.INFO,
                    "sql.executed",
                    pipeline="sync",
                    attempt=attempt,
                    sql=sql,
                    row_count=len(candidate.get("rows", [])),
                )
                break
            last_error = candidate.get("error") or "Unknown SQL execution error."
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="execution", sql=sql, error=last_error))
            log_event(
                logger,
                logging.WARNING,
                "sql.execution_failed",
                pipeline="sync",
                attempt=attempt,
                sql=sql,
                error=last_error,
            )
            if reused_correction and not memory_fallback_attempted:
                try:
                    sql = _generate_sql_with_llm()
                    sql_source = "llm"
                    memory_fallback_attempted = True
                    log_event(
                        logger,
                        logging.INFO,
                        "sql.memory_fallback_to_llm",
                        pipeline="sync",
                        failed_memory_sql=attempts[-1].sql,
                        error=last_error,
                    )
                    continue
                except Exception as e:
                    log_event(
                        logger,
                        logging.ERROR,
                        "sql.generation_failed_after_memory_fallback",
                        pipeline="sync",
                        error=str(e),
                    )
                    result = {
                        "ok": False,
                        "route": "ERROR",
                        "stage": "sql_generation",
                        "message": sql_generation_failed_message(e),
                    }
                    return _finalize(result, level=logging.ERROR, event="pipeline.failed", error=str(e))

        if attempt == max_attempts:
            break

        try:
            sql = error_agent.repair_sql(
                question=question,
                schema_text=schema_text,
                failed_sql=sql,
                error_message=last_error,
            )
            log_event(
                logger,
                logging.INFO,
                "sql.repaired",
                pipeline="sync",
                attempt=attempt,
                sql=sql,
            )
        except Exception as e:
            last_error = sql_repair_failed_message(e)
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="repair", sql=sql, error=last_error))
            log_event(
                logger,
                logging.ERROR,
                "sql.repair_failed",
                pipeline="sync",
                attempt=attempt,
                sql=sql,
                error=last_error,
            )
            break

    if exec_res is None:
        result = {
            "ok": False,
            "route": "ERROR",
            "stage": "error_recovery",
            "sql": sql,
            "error": last_error or "Failed to produce a valid executable SQL query.",
            "attempts": [asdict(a) for a in attempts],
            "message": FAILED_EXECUTABLE_SQL_MESSAGE,
        }
        return _finalize(
            result,
            level=logging.ERROR,
            event="pipeline.failed",
            sql=sql,
            error=last_error or FAILED_EXECUTABLE_SQL_MESSAGE,
        )

    columns = exec_res.get("columns", [])
    rows = exec_res.get("rows", [])
    formatted = format_response_dict(columns, rows)
    result_object = build_result_object(
        columns,
        rows,
        sql=sql,
        question=question,
        summary_text=formatted["text"],
        context_filters=getattr(gk, "filters", {}) or {},
        current_grouping=getattr(gk, "dimensions", []) or [],
        time_reference=(
            getattr(gk, "time_range", None).model_dump()
            if getattr(gk, "time_range", None) is not None
            else {}
        ),
        entity_focus=getattr(gk, "metric", None) or "",
    )
    answer_text = analysis_agent.summarize(
        question=question,
        sql=sql,
        columns=columns,
        rows=rows,
        fallback_text=formatted["text"],
    )
    if can_visualize(columns, rows):
        answer_text = with_plot_suggestion(answer_text)
    conversation_state = build_conversation_state(
        question=question,
        route="DATA",
        sql=sql,
        result_object=result_object,
        metric=getattr(gk, "metric", None) or "",
        dimensions=getattr(gk, "dimensions", []) or [],
        time_range=(
            getattr(gk, "time_range", None).model_dump()
            if getattr(gk, "time_range", None) is not None
            else {}
        ),
        filters=getattr(gk, "filters", {}) or {},
        sort_by="",
        sort_direction="",
        aggregation_intent="",
        last_user_intent=getattr(gk, "parsed_intent", "") or "data_query",
        answer_text=answer_text,
    )
    result = {
        "ok": True,
        "route": "DATA",
        "stage": "done",
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "answer_text": answer_text,
        "answer_table": formatted["table"],
        "preview_rows": formatted["preview_rows"],
        "preview_row_count": formatted["preview_row_count"],
        "total_rows": formatted["total_rows"],
        "attempts": [asdict(a) for a in attempts],
        "retry_count": max(0, len(attempts) - 1),
        "reused_correction": reused_correction,
        "sql_source": sql_source,
        "result_object": result_object,
        "conversation_state": conversation_state,
    }
    return _finalize(
        result,
        level=logging.INFO,
        event="pipeline.completed",
        sql=sql,
        row_count=len(rows),
        retry_count=max(0, len(attempts) - 1),
    )
