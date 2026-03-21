"""
LangGraph version of the same multi-agent workflow.

Connection in flow:
- Upstream: built via app.pipeline.build_text2sql_graph() when you switch to graph runtime.
- This file: maps each agent into a LangGraph node with conditional edges.
- Downstream: compiled graph can stream events or run invoke() for production.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from app.agents.analysis_agent import AnalysisAgent
from app.agents.error_agent import ErrorAgent
from app.agents.guardrail_agent import GuardrailsAgent
from app.agents.sql_agent import SQLAgent
from app.agents.viz_agent import VizAgent
from app.db.sqlite import get_schema_text
from app.formatters.format_response import format_response_dict
from app.formatters.viz_plotly import infer_plotly
from app.pipeline.execute_sql import execute_sql
from app.safety.sql_validator import validate_sql

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover
    END = None
    StateGraph = None


class AgentState(TypedDict, total=False):
    db_path: str
    question: str
    schema_text: str
    status: str
    route: str
    sql: str
    error: str
    attempts: List[Dict[str, Any]]
    columns: List[str]
    rows: List[Any]
    answer_text: str
    answer_table: str
    preview_rows: List[List[str]]
    preview_row_count: int
    total_rows: int
    viz: Optional[Dict[str, Any]]
    retry_count: int
    missing_slots: List[str]
    clarifying_questions: List[str]


def build_text2sql_graph(max_sql_repair_attempts: int = 3):
    """
    Build a LangGraph workflow with nodes:
    guardrails_agent -> sql_agent -> execute_sql -> error_agent -> analysis_agent -> viz_agent
    """
    if StateGraph is None or END is None:
        raise ImportError("langgraph is not installed. Add `langgraph` to requirements and install dependencies.")

    guardrails_agent = GuardrailsAgent()
    sql_agent = SQLAgent()
    error_agent = ErrorAgent()
    analysis_agent = AnalysisAgent()
    viz_agent = VizAgent()

    workflow = StateGraph(AgentState)

    def guardrails_node(state: AgentState) -> AgentState:
        question = state.get("question", "")
        db_path = state.get("db_path", "")
        schema_text = state.get("schema_text") or get_schema_text(db_path)
        gk = guardrails_agent.evaluate(question)
        out: AgentState = {
            "schema_text": schema_text,
            "status": gk.status,
            "missing_slots": list(getattr(gk, "missing_slots", []) or []),
            "clarifying_questions": list(getattr(gk, "clarifying_questions", []) or []),
        }
        if gk.status == "OUT OF SCOPE":
            out["route"] = "OUT_OF_SCOPE"
            out["answer_text"] = "Request refused by safety policy."
        elif gk.status == "NEEDS CLARIFICATION":
            out["route"] = "CLARIFY"
            qs = out["clarifying_questions"]
            out["answer_text"] = qs[0] if qs else "Could you clarify your request?"
        else:
            out["route"] = "DATA"
        return out

    def sql_node(state: AgentState) -> AgentState:
        sql = sql_agent.generate_sql(state["question"], state["schema_text"])
        return {"sql": sql, "error": "", "attempts": state.get("attempts", [])}

    def execute_node(state: AgentState) -> AgentState:
        sql = state.get("sql", "")
        attempts = list(state.get("attempts", []))

        ok, reason = validate_sql(sql)
        if not ok:
            attempts.append({"stage": "validation", "sql": sql, "error": reason})
            return {"error": f"SQL validation failed: {reason}", "attempts": attempts}

        res = execute_sql(state["db_path"], sql)
        if not res.get("ok"):
            err = res.get("error", "Unknown SQL execution error.")
            attempts.append({"stage": "execution", "sql": sql, "error": err})
            return {"error": err, "attempts": attempts}

        attempts.append({"stage": "execution", "sql": sql, "error": ""})
        return {
            "error": "",
            "attempts": attempts,
            "columns": res.get("columns", []),
            "rows": res.get("rows", []),
        }

    def error_node(state: AgentState) -> AgentState:
        attempts = list(state.get("attempts", []))
        sql = error_agent.repair_sql(
            question=state["question"],
            schema_text=state["schema_text"],
            failed_sql=state.get("sql", ""),
            error_message=state.get("error", ""),
        )
        attempts.append({"stage": "repair", "sql": sql, "error": ""})
        return {"sql": sql, "attempts": attempts, "error": ""}

    def analysis_node(state: AgentState) -> AgentState:
        cols = state.get("columns", [])
        rows = state.get("rows", [])
        formatted = format_response_dict(cols, rows)
        answer_text = analysis_agent.summarize(
            question=state.get("question", ""),
            sql=state.get("sql", ""),
            columns=cols,
            rows=rows,
            fallback_text=formatted["text"],
        )
        return {
            "answer_text": answer_text,
            "answer_table": formatted["table"],
            "preview_rows": formatted["preview_rows"],
            "preview_row_count": formatted["preview_row_count"],
            "total_rows": formatted["total_rows"],
            "retry_count": max(0, len(state.get("attempts", [])) - 1),
        }

    def viz_node(state: AgentState) -> AgentState:
        cols = state.get("columns", [])
        rows = state.get("rows", [])
        fallback = infer_plotly(state.get("question", ""), cols, rows)
        viz = viz_agent.generate(
            question=state.get("question", ""),
            columns=cols,
            rows=rows,
            fallback_viz=fallback,
        )
        return {"viz": viz}

    def check_guardrails(state: AgentState) -> str:
        route = state.get("route", "OUT_OF_SCOPE")
        if route == "DATA":
            return "in_scope"
        return "blocked"

    def check_execution(state: AgentState) -> str:
        if not state.get("error"):
            return "success"
        repair_count = sum(1 for a in state.get("attempts", []) if a.get("stage") == "repair")
        if repair_count < max_sql_repair_attempts:
            return "retry"
        return "end"

    workflow.add_node("guardrails_agent", guardrails_node)
    workflow.add_node("sql_agent", sql_node)
    workflow.add_node("execute_sql", execute_node)
    workflow.add_node("error_agent", error_node)
    workflow.add_node("analysis_agent", analysis_node)
    workflow.add_node("viz_agent", viz_node)

    workflow.set_entry_point("guardrails_agent")
    workflow.add_conditional_edges(
        "guardrails_agent",
        check_guardrails,
        {
            "in_scope": "sql_agent",
            "blocked": END,
        },
    )
    workflow.add_edge("sql_agent", "execute_sql")
    workflow.add_conditional_edges(
        "execute_sql",
        check_execution,
        {
            "success": "analysis_agent",
            "retry": "error_agent",
            "end": END,
        },
    )
    workflow.add_edge("error_agent", "execute_sql")
    workflow.add_edge("analysis_agent", "viz_agent")
    workflow.add_edge("viz_agent", END)

    return workflow.compile()
