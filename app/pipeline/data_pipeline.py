"""
Synchronous orchestration pipeline used by the app today.

Connection in flow:
- Upstream: called by streamlit_app.py and app/main.py.
- This file: runs guardrails -> sql -> validate/execute -> error-retry -> analysis -> viz.
- Downstream: returns one response dict consumed by UI and CLI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List
from app.db.sqlite import get_schema_text

from app.agents.analysis_agent import AnalysisAgent
from app.agents.error_agent import ErrorAgent
from app.agents.guardrail_agent import GuardrailsAgent
from app.agents.sql_agent import SQLAgent
from app.agents.viz_agent import VizAgent
from app.safety.sql_validator import validate_sql
from app.pipeline.execute_sql import execute_sql
from app.formatters.viz_plotly import infer_plotly

from app.formatters.format_response import format_response_dict

MAX_SQL_REPAIR_ATTEMPTS = 3


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
    schema_text = get_schema_text(db_path)
    guardrails_agent = GuardrailsAgent()
    sql_agent = SQLAgent()
    error_agent = ErrorAgent()
    analysis_agent = AnalysisAgent()
    viz_agent = VizAgent()

    # Guardrails / scope check
    gk = guardrails_agent.evaluate(question)
    if gk.status == "OUT OF SCOPE":
        return {
            "ok": False,
            "route": "OUT_OF_SCOPE",
            "stage": "guardrails_agent",
            "status": gk.status,
            "reason": gk.parsed_intent,
            "message": "Request refused by safety policy.",
            "notes": gk.notes,
        }
    if gk.status == "NEEDS CLARIFICATION":
        clarifying_questions = _get_clarifying_questions(gk)
        return {
            "ok": False,
            "route": "CLARIFY",
            "stage": "guardrails_agent",
            "status": gk.status,
            "message": "Need clarification before querying the database.",
            "question": clarifying_questions[0] if clarifying_questions else "Could you clarify your request?",
            "clarifying_questions": clarifying_questions,
            "missing_slots": gk.missing_slots,
            "notes": gk.notes,
        }

    attempts: List[SQLAttemptTrace] = []
    max_attempts = 1 + MAX_SQL_REPAIR_ATTEMPTS

    try:
        sql = sql_agent.generate_sql(question, schema_text=schema_text)
    except Exception as e:
        return {
            "ok": False,
            "route": "ERROR",
            "stage": "sql_generation",
            "message": f"SQL generation failed: {type(e).__name__}: {e}",
        }

    exec_res: Dict[str, Any] | None = None
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        is_ok, reason = validate_sql(sql)
        if not is_ok:
            last_error = f"SQL validation failed: {reason}"
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="validation", sql=sql, error=last_error))
        else:
            candidate = execute_sql(db_path, sql)
            if candidate.get("ok"):
                exec_res = candidate
                attempts.append(SQLAttemptTrace(attempt=attempt, stage="execution", sql=sql))
                break
            last_error = candidate.get("error") or "Unknown SQL execution error."
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="execution", sql=sql, error=last_error))

        if attempt == max_attempts:
            break

        try:
            sql = error_agent.repair_sql(
                question=question,
                schema_text=schema_text,
                failed_sql=sql,
                error_message=last_error,
            )
        except Exception as e:
            last_error = f"SQL repair failed: {type(e).__name__}: {e}"
            attempts.append(SQLAttemptTrace(attempt=attempt, stage="repair", sql=sql, error=last_error))
            break

    if exec_res is None:
        return {
            "ok": False,
            "route": "ERROR",
            "stage": "error_recovery",
            "sql": sql,
            "error": last_error or "Failed to produce a valid executable SQL query.",
            "attempts": [asdict(a) for a in attempts],
            "message": "I couldn't produce a valid SQL query after several repair attempts.",
        }

    columns = exec_res.get("columns", [])
    rows = exec_res.get("rows", [])
    formatted = format_response_dict(columns, rows)
    answer_text = analysis_agent.summarize(
        question=question,
        sql=sql,
        columns=columns,
        rows=rows,
        fallback_text=formatted["text"],
    )
    viz = viz_agent.generate(
        question=question,
        columns=columns,
        rows=rows,
        fallback_viz=infer_plotly(question, columns, rows),
    )

    return {
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
        "viz": viz,
        "attempts": [asdict(a) for a in attempts],
        "retry_count": max(0, len(attempts) - 1),
    }
