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

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from app.agents.analysis_agent import AnalysisAgent
from app.agents.error_agent import ErrorAgent
from app.agents.guardrails.agent import GuardrailsAgent
from app.agents.sql.agent import SQLAgent
from app.agents.viz_agent import VizAgent
from app.db.corrections import fetch_similar_correction
from app.db.sqlite import get_schema_text
from app.formatters.format_response import format_response_dict, with_plot_suggestion
from app.formatters.viz_plotly import infer_plotly
from app.llm.factory import LLMConfigurationError
from app.logging_utils import get_logger, log_event
from app.messages import (
    CLARIFY_REQUEST_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    PIPELINE_NONE_MESSAGE,
    GREETING_RESPONSES,
    VIZ_NO_DATA_MESSAGE,
    pipeline_error_message,
)
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
    reused_correction: bool
    sql_source: str
    needs_execute_retry: bool
    memory_fallback_attempted: bool

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
logger = get_logger(__name__)


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
            log_event(
                logger,
                logging.INFO,
                "graph.context_resolved",
                resolved_intent="clarification_merged",
                prior_route=prior_route,
                question_preview=question[:120],
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
                viz_question = "{} - {}".format(question, prior_question) if prior_question else question
                log_event(
                    logger,
                    logging.INFO,
                    "graph.context_resolved",
                    resolved_intent="viz_followup",
                    prior_route=prior_route,
                    question_preview=question[:120],
                )
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
                    "answer_text": VIZ_NO_DATA_MESSAGE,
                }

        # Case 3: normal new query
        log_event(
            logger,
            logging.INFO,
            "graph.context_resolved",
            resolved_intent="new_query",
            prior_route=prior_route,
            question_preview=question[:120],
        )
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
                out["answer_text"] = getattr(gk, "notes", "") or GREETING_RESPONSES[0]
            else:
                out["route"] = "OUT_OF_SCOPE"
                out["answer_text"] = OUT_OF_SCOPE_MESSAGE
        elif gk.status == "NEEDS CLARIFICATION":
            out["route"] = "CLARIFY"
            qs = out["clarifying_questions"]
            out["answer_text"] = qs[0] if qs else CLARIFY_REQUEST_MESSAGE
        else:
            out["route"] = "DATA"
        log_event(
            logger,
            logging.INFO,
            "graph.guardrails_decision",
            route=out.get("route"),
            status=gk.status,
            reason=getattr(gk, "parsed_intent", ""),
            missing_slots=out.get("missing_slots", []),
        )
        return out

    # ---- Node: sql_agent ----
    def sql_node(state: AgentState) -> AgentState:
        remembered_sql = fetch_similar_correction(state["db_path"], state["question"])
        if remembered_sql:
            log_event(
                logger,
                logging.INFO,
                "graph.sql_reused_from_memory",
                route=state.get("route"),
                sql=remembered_sql,
            )
            return {
                "sql": remembered_sql,
                "sql_source": "expert_memory",
                "reused_correction": True,
                "memory_fallback_attempted": False,
                "needs_execute_retry": False,
                "error": "",
                "attempts": state.get("attempts", []),
            }

        sql = sql_agent.generate_sql(state["question"], state["schema_text"])
        log_event(
            logger,
            logging.INFO,
            "graph.sql_generated",
            route=state.get("route"),
            sql=sql,
        )
        return {
            "sql": sql,
            "sql_source": "llm",
            "reused_correction": False,
            "memory_fallback_attempted": False,
            "needs_execute_retry": False,
            "error": "",
            "attempts": state.get("attempts", []),
        }

    # ---- Node: execute_sql ----
    def execute_node(state: AgentState) -> AgentState:
        sql = state.get("sql", "")
        attempts = list(state.get("attempts", []))

        ok, reason = validate_sql(sql)
        if not ok:
            attempts.append({"stage": "validation", "sql": sql, "error": reason})
            log_event(
                logger,
                logging.WARNING,
                "graph.sql_validation_failed",
                sql=sql,
                error=reason,
            )
            if state.get("sql_source") == "expert_memory" and not state.get("memory_fallback_attempted"):
                fallback_sql = sql_agent.generate_sql(state["question"], state["schema_text"])
                log_event(
                    logger,
                    logging.INFO,
                    "graph.sql_memory_fallback_to_llm",
                    failed_memory_sql=sql,
                    error=reason,
                    replacement_sql=fallback_sql,
                )
                return {
                    "sql": fallback_sql,
                    "sql_source": "llm",
                    "memory_fallback_attempted": True,
                    "needs_execute_retry": True,
                    "error": "",
                    "attempts": attempts,
                }
            return {
                "error": "SQL validation failed: {}".format(reason),
                "attempts": attempts,
                "needs_execute_retry": False,
            }

        res = execute_sql(state["db_path"], sql)
        if not res.get("ok"):
            err = res.get("error", "Unknown SQL execution error.")
            attempts.append({"stage": "execution", "sql": sql, "error": err})
            log_event(
                logger,
                logging.WARNING,
                "graph.sql_execution_failed",
                sql=sql,
                error=err,
            )
            if state.get("sql_source") == "expert_memory" and not state.get("memory_fallback_attempted"):
                fallback_sql = sql_agent.generate_sql(state["question"], state["schema_text"])
                log_event(
                    logger,
                    logging.INFO,
                    "graph.sql_memory_fallback_to_llm",
                    failed_memory_sql=sql,
                    error=err,
                    replacement_sql=fallback_sql,
                )
                return {
                    "sql": fallback_sql,
                    "sql_source": "llm",
                    "memory_fallback_attempted": True,
                    "needs_execute_retry": True,
                    "error": "",
                    "attempts": attempts,
                }
            return {"error": err, "attempts": attempts, "needs_execute_retry": False}

        attempts.append({"stage": "execution", "sql": sql, "error": ""})
        log_event(
            logger,
            logging.INFO,
            "graph.sql_executed",
            sql=sql,
            row_count=len(res.get("rows", [])),
        )
        return {
            "error": "",
            "attempts": attempts,
            "columns": res.get("columns", []),
            "rows": res.get("rows", []),
            "needs_execute_retry": False,
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
        log_event(
            logger,
            logging.INFO,
            "graph.sql_repaired",
            sql=sql,
            repair_count=sum(1 for a in attempts if a.get("stage") == "repair"),
        )
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
        answer_text = with_plot_suggestion(answer_text)
        log_event(
            logger,
            logging.INFO,
            "graph.analysis_completed",
            row_count=len(rows),
            retry_count=max(0, len(state.get("attempts", [])) - 1),
        )

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
        log_event(
            logger,
            logging.INFO,
            "graph.viz_generated",
            has_viz=bool(viz),
            row_count=len(rows),
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
        if state.get("needs_execute_retry"):
            return "retry_execute"
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
            "retry_execute": "execute_sql",
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


def _get_prior_state(graph_app, config: dict) -> dict:
    """Read the previous turn's final state from the LangGraph checkpoint."""
    try:
        snapshot = graph_app.get_state(config)
        if snapshot and snapshot.values:
            return dict(snapshot.values)
    except Exception:
        pass
    return {}


def invoke_graph_pipeline(
    *,
    db_path: str,
    question: str,
    thread_id: str,
    graph_app=None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Invoke the canonical LangGraph runtime used by the UI.

    Returns a tuple of:
    - result: final graph state/result payload
    - prior: previous checkpoint state used as memory context
    """
    try:
        graph_app = graph_app or get_graph_app()
    except LLMConfigurationError as exc:
        log_event(
            logger,
            logging.ERROR,
            "graph.setup_failed",
            thread_id=thread_id,
            error=str(exc),
        )
        return {"route": "ERROR", "answer_text": str(exc)}, {}

    config = {"configurable": {"thread_id": thread_id}}
    prior = _get_prior_state(graph_app, config)
    log_event(
        logger,
        logging.INFO,
        "graph.invoke_started",
        thread_id=thread_id,
        question_preview=question[:120],
        prior_route=prior.get("route", ""),
    )

    input_state = {
        "question": question,
        "db_path": db_path,
        "prior_question": prior.get("question", ""),
        "prior_route": prior.get("route", ""),
        "prior_missing_slots": prior.get("missing_slots", []),
        "prior_clarifying_questions": prior.get("clarifying_questions", []),
        "prior_columns": prior.get("columns", []),
        "prior_rows": prior.get("preview_rows", prior.get("rows", [])),
        "prior_sql": prior.get("sql", ""),
    }

    try:
        result = graph_app.invoke(input_state, config=config)
        if result is None:
            result = {"route": "ERROR", "answer_text": PIPELINE_NONE_MESSAGE}
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            "graph.invoke_failed",
            thread_id=thread_id,
            error=str(e),
        )
        result = {"route": "ERROR", "answer_text": pipeline_error_message(e)}

    log_event(
        logger,
        logging.INFO,
        "graph.invoke_completed",
        thread_id=thread_id,
        route=result.get("route", ""),
        status=result.get("status", ""),
        retry_count=result.get("retry_count", 0),
        reused_correction=result.get("reused_correction", False),
        sql_source=result.get("sql_source", ""),
    )

    return result, prior
