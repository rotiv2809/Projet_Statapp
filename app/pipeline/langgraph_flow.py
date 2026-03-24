"""
LangGraph version of the multi-agent workflow with conversation memory.

Connection in flow:
- Upstream: built via get_graph_app() for Streamlit / CLI usage.
- This file: maps each agent into a LangGraph node with conditional edges
  and adds a context_resolver node for multi-turn memory (slot filling,
  post-result follow-ups like "plot it").
- Downstream: compiled graph uses MemorySaver to persist state across turns
  within the same thread_id.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, TypedDict

from app.agents.analysis_agent import AnalysisAgent
from app.agents.error_agent import ErrorAgent
from app.agents.guardrails.agent import GuardrailsAgent
from app.agents.sql.agent import SQLAgent
from app.agents.viz_agent import VizAgent
from app.db.sqlite import get_schema_text
from app.formatters.format_response import format_response_dict
from app.formatters.viz_plotly import infer_plotly
from app.pipeline.execute_sql import execute_sql
from app.safety.sql_validator import validate_sql

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class AgentState(TypedDict, total=False):
    # -- core fields --
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

    # -- memory / multi-turn context (injected before invoke) --
    resolved_intent: str
    prior_question: str
    prior_route: str
    prior_missing_slots: List[str]
    prior_clarifying_questions: List[str]
    prior_columns: List[str]
    prior_rows: List[Any]
    prior_sql: str


_VIZ_FOLLOWUP_RE = re.compile(
    r"\b(plot|chart|graph|visuali[sz]e|"
    r"show\s+(me\s+)?(a\s+)?(chart|graph|plot)|"
    r"draw|diagram|histogram|bar\s*chart|pie\s*chart)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_text2sql_graph(max_sql_repair_attempts: int = 3):
    """
    Build a LangGraph workflow:
    context_resolver -> guardrails_agent -> sql_agent -> execute_sql
                                                         -> error_agent (retry)
                                                         -> analysis_agent -> END
    context_resolver can short-circuit to viz_agent for explicit viz follow-ups,
    or to END for blocked/viz_no_data routes.
    """
    guardrails_agent = GuardrailsAgent()
    sql_agent = SQLAgent()
    error_agent = ErrorAgent()
    analysis_agent = AnalysisAgent()
    viz_agent = VizAgent()

    workflow = StateGraph(AgentState)

    # ---- Node: context_resolver (multi-turn memory) ----
    def context_resolver_node(state: AgentState) -> AgentState:
        question = state.get("question", "")
        prior_route = state.get("prior_route", "")
        prior_question = state.get("prior_question", "")
        prior_missing_slots = state.get("prior_missing_slots", [])

        # Case 1: previous turn asked for clarification
        if prior_route == "CLARIFY" and prior_question:
            slot_info = ""
            if prior_missing_slots:
                slot_info = " (filling slots: {})".format(", ".join(prior_missing_slots))
            resolved = "{}\nUser clarification{}: {}".format(
                prior_question, slot_info, question
            )
            return {"question": resolved, "resolved_intent": "clarification_merged"}

        # Case 2: user asks for a visualization
        if _VIZ_FOLLOWUP_RE.search(question):
            prior_cols = state.get("prior_columns", [])
            prior_rows = state.get("prior_rows", [])
            if prior_cols and prior_rows:
                # Combine the user's viz request with the original data question
                # so the viz agent sees chart-type hints (e.g. "pie chart")
                # while also knowing the data context.
                viz_question = "{} — {}".format(question, prior_question) if prior_question else question
                return {
                    "question": viz_question,
                    "columns": prior_cols,
                    "rows": prior_rows,
                    "sql": state.get("prior_sql", ""),
                    "resolved_intent": "viz_followup",
                    "route": "VIZ_FOLLOWUP",
                }
            else:
                # Viz requested but no prior data to plot
                return {
                    "resolved_intent": "viz_no_data",
                    "route": "VIZ_NO_DATA",
                    "answer_text": (
                        "I don't have any data to plot yet. "
                        "Try asking a data question first, then I can visualize the results!"
                    ),
                }

        # Case 3: normal new query
        return {"resolved_intent": "new_query"}

    # ---- Node: guardrails ----
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
            if getattr(gk, "parsed_intent", "") == "greeting":
                out["route"] = "CHAT"
                out["answer_text"] = getattr(gk, "notes", "") or "Hello!"
            else:
                out["route"] = "OUT_OF_SCOPE"
                out["answer_text"] = "I'm designed for data analytics questions about clients, transactions, and dossiers. Could you rephrase your question around those topics?"
        elif gk.status == "NEEDS CLARIFICATION":
            out["route"] = "CLARIFY"
            qs = out["clarifying_questions"]
            out["answer_text"] = qs[0] if qs else "Could you clarify your request?"
        else:
            out["route"] = "DATA"
        return out

    # ---- Node: sql_agent ----
    def sql_node(state: AgentState) -> AgentState:
        sql = sql_agent.generate_sql(state["question"], state["schema_text"])
        return {"sql": sql, "error": "", "attempts": state.get("attempts", [])}

    # ---- Node: execute_sql ----
    def execute_node(state: AgentState) -> AgentState:
        sql = state.get("sql", "")
        attempts = list(state.get("attempts", []))

        ok, reason = validate_sql(sql)
        if not ok:
            attempts.append({"stage": "validation", "sql": sql, "error": reason})
            return {"error": "SQL validation failed: {}".format(reason), "attempts": attempts}

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

    # ---- Node: error_agent ----
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

    # ---- Node: analysis_agent ----
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
        # Append a plot suggestion so user knows they can ask for a chart
        answer_text += "\n\n📊 *I can plot this data for you — just ask! (e.g. \"plot a bar chart\" or \"show me a pie chart\")*"

        return {
            "answer_text": answer_text,
            "answer_table": formatted["table"],
            "preview_rows": formatted["preview_rows"],
            "preview_row_count": formatted["preview_row_count"],
            "total_rows": formatted["total_rows"],
            "retry_count": max(0, len(state.get("attempts", [])) - 1),
        }

    # ---- Node: viz_agent ----
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

    # ---- Routing functions ----
    def check_context(state: AgentState) -> str:
        intent = state.get("resolved_intent", "new_query")
        if intent == "viz_followup":
            return "viz_direct"
        if intent == "viz_no_data":
            return "blocked"
        return "guardrails"

    def check_guardrails(state: AgentState) -> str:
        route = state.get("route", "OUT_OF_SCOPE")
        if route == "DATA":
            return "in_scope"
        return "blocked"

    def check_execution(state: AgentState) -> str:
        if not state.get("error"):
            return "success"
        repair_count = sum(
            1 for a in state.get("attempts", []) if a.get("stage") == "repair"
        )
        if repair_count < max_sql_repair_attempts:
            return "retry"
        return "end"

    # ---- Wire nodes ----
    workflow.add_node("context_resolver", context_resolver_node)
    workflow.add_node("guardrails_agent", guardrails_node)
    workflow.add_node("sql_agent", sql_node)
    workflow.add_node("execute_sql", execute_node)
    workflow.add_node("error_agent", error_node)
    workflow.add_node("analysis_agent", analysis_node)
    workflow.add_node("viz_agent", viz_node)

    # ---- Wire edges ----
    workflow.set_entry_point("context_resolver")
    workflow.add_conditional_edges(
        "context_resolver",
        check_context,
        {
            "viz_direct": "viz_agent",
            "guardrails": "guardrails_agent",
            "blocked": END,
        },
    )
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
    workflow.add_edge("analysis_agent", END)
    workflow.add_edge("viz_agent", END)

    return workflow


# ---------------------------------------------------------------------------
# Application singleton  (used by streamlit_app.py)
# ---------------------------------------------------------------------------

_app_instance = None
_memory_instance = None


def get_graph_app():
    """Return a compiled LangGraph app with MemorySaver for multi-turn memory."""
    global _app_instance, _memory_instance
    if _app_instance is None:
        _memory_instance = MemorySaver()
        workflow = build_text2sql_graph()
        _app_instance = workflow.compile(checkpointer=_memory_instance)
    return _app_instance
