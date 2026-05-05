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
from app.db.sqlite import get_prompt_schema_text, get_schema_text
from app.formatters.format_response import format_response_dict, with_plot_suggestion
from app.formatters.viz_plotly import (
    build_visualization_guidance,
    can_visualize,
    infer_plotly,
    requested_chart_type,
    supports_visualization_request,
)
from app.llm.factory import LLMConfigurationError
from app.logging_utils import get_logger, log_event
from app.messages import (
    CLARIFY_REQUEST_MESSAGE,
    PIPELINE_NONE_MESSAGE,
    pipeline_error_message,
)
from app.pipeline.execute_sql import execute_sql
from app.pipeline.chatbot_orchestrator import (
    build_direct_assistant_response,
    build_normalized_request,
    classify_turn_intent,
    has_active_analysis_context,
)
from app.pipeline.conversation_state import (
    build_conversation_state,
    build_result_object,
    should_reuse_result_for_chart,
)
from app.pipeline.response_policy import (
    build_out_of_scope_answer,
    build_viz_no_data_answer,
    compose_data_answer,
)
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
    parsed_intent: str
    metric: str
    dimensions: List[str]
    time_range: Dict[str, Any]
    filters: Dict[str, Any]
    sort_by: str
    sort_direction: str
    aggregation_intent: str
    reused_correction: bool
    sql_source: str
    needs_execute_retry: bool
    memory_fallback_attempted: bool
    result_object: Dict[str, Any]
    conversation_state: Dict[str, Any]
    normalized_request: Dict[str, Any]

    # -- memory / multi-turn context (injected before invoke) --
    resolved_intent: str
    prior_question: str
    prior_route: str
    prior_missing_slots: List[str]
    prior_clarifying_questions: List[str]
    prior_columns: List[str]
    prior_rows: List[Any]
    prior_sql: str
    prior_metric: str
    prior_dimensions: List[str]
    prior_time_range: Dict[str, Any]
    prior_filters: Dict[str, Any]
    prior_sort_by: str
    prior_sort_direction: str
    prior_aggregation_intent: str
    prior_result_object: Dict[str, Any]
    prior_conversation_state: Dict[str, Any]


_YEAR_RE = re.compile(r"\b(20\d{2})\b")
logger = get_logger(__name__)


def _extract_query_memory(question: str) -> Dict[str, Any]:
    q = (question or "").strip()
    lower = q.lower()
    dimensions: List[str] = []
    filters: Dict[str, Any] = {}
    metric = ""
    aggregation_intent = ""
    sort_by = ""
    sort_direction = ""
    time_range: Dict[str, Any] = {}

    for label in ("segment", "commune", "pays", "country", "enseigne", "categorie_achat", "month", "year"):
        if re.search(r"\b{}\b".format(re.escape(label)), lower):
            dimensions.append(label)

    year_match = _YEAR_RE.search(q)
    if year_match:
        time_range = {"kind": "year", "value": year_match.group(1)}

    if re.search(r"\bhow many clients\b|\bnumber of clients\b", lower):
        metric = "clients"
        aggregation_intent = "count"
    elif re.search(r"\bhow many transactions\b|\bnumber of transactions\b", lower):
        metric = "transactions"
        aggregation_intent = "count"
    elif re.search(r"\btotal amount\b|\bmontant total\b|\bsum\b", lower):
        metric = "amount"
        aggregation_intent = "sum"
    elif re.search(r"\baverage\b|\bavg\b|\bmoyenne\b", lower):
        aggregation_intent = "average"
    elif re.search(r"\bcompare\b", lower):
        aggregation_intent = "comparison"
    elif re.search(r"\btrend\b|\bover time\b", lower):
        aggregation_intent = "trend"

    if re.search(r"\btop\b|\bhighest\b|\bbest\b", lower):
        sort_direction = "desc"
        sort_by = metric or "value"
    elif re.search(r"\blowest\b|\bworst\b", lower):
        sort_direction = "asc"
        sort_by = metric or "value"
    elif re.search(r"\bdescending\b|\bdesc\b", lower):
        sort_direction = "desc"
        sort_by = metric or "value"
    elif re.search(r"\bascending\b|\basc\b", lower):
        sort_direction = "asc"
        sort_by = metric or "value"

    filter_match = re.search(
        r"\b(?:for|in)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b(?:\s+only)?\??$",
        q,
    )
    if filter_match and not _YEAR_RE.search(filter_match.group(1)):
        filters["scope"] = filter_match.group(1)

    return {
        "metric": metric,
        "dimensions": dimensions,
        "time_range": time_range,
        "filters": filters,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "aggregation_intent": aggregation_intent,
    }


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
        schema_text = state.get("schema_text") or get_prompt_schema_text(
            state.get("db_path", ""),
            question,
        )
        prior_result_object = dict(state.get("prior_result_object") or {})
        prior_conversation_state = dict(
            state.get("prior_conversation_state")
            or {
                "metric": state.get("prior_metric", ""),
                "current_grouping": state.get("prior_dimensions", []),
                "current_time_reference": state.get("prior_time_range", {}),
                "current_filters": state.get("prior_filters", {}),
                "sort_by": state.get("prior_sort_by", ""),
                "sort_direction": state.get("prior_sort_direction", ""),
                "aggregation_intent": state.get("prior_aggregation_intent", ""),
                "last_result_object": prior_result_object,
            }
        )
        intent = classify_turn_intent(question, prior_conversation_state, prior_route)
        direct_response = build_direct_assistant_response(question, intent, prior_conversation_state)
        if direct_response:
            direct_response["resolved_intent"] = intent
            return direct_response
        normalized_request = build_normalized_request(
            question=question,
            intent=intent,
            conversation_state=prior_conversation_state,
            schema_text=schema_text,
        )

        # Case 1: previous turn asked for clarification
        if prior_route == "CLARIFY" and prior_question and intent == "clarification_reply":
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

        if normalized_request.get("needs_clarification"):
            return {
                "route": "CLARIFY",
                "answer_text": normalized_request.get("clarification_message", CLARIFY_REQUEST_MESSAGE),
                "clarifying_questions": [normalized_request.get("clarification_message", CLARIFY_REQUEST_MESSAGE)],
                "normalized_request": normalized_request,
                "resolved_intent": intent,
            }

        # Case 2: user asks for a visualization of the existing result
        if intent == "visualization_request" and should_reuse_result_for_chart(question, prior_conversation_state):
            chart_source = (
                prior_conversation_state.get("last_chartable_result")
                or prior_result_object
                or prior_conversation_state.get("last_result_object")
                or {}
            )
            prior_cols = chart_source.get("columns") or state.get("prior_columns", [])
            prior_rows = chart_source.get("rows") or state.get("prior_rows", [])
            if chart_source.get("chart_ready") and prior_cols and prior_rows:
                viz_question = "{} - {}".format(question, prior_question) if prior_question else question
                log_event(
                    logger,
                    logging.INFO,
                    "graph.context_resolved",
                    resolved_intent="viz_followup",
                    prior_route=prior_route,
                    question_preview=question[:120],
                )
                updated_conversation_state = dict(prior_conversation_state)
                updated_conversation_state["last_user_intent"] = "chart_request"
                updated_conversation_state["last_user_question"] = question
                return {
                    "question": viz_question,
                    "columns": prior_cols,
                    "rows": prior_rows,
                    "sql": chart_source.get("sql") or state.get("prior_sql", ""),
                    "result_object": chart_source,
                    "conversation_state": updated_conversation_state,
                    "normalized_request": normalized_request,
                    "resolved_intent": "viz_followup",
                    "route": "VIZ_FOLLOWUP",
                }
            if chart_source:
                return {
                    "resolved_intent": "viz_unsupported",
                    "route": "VIZ_UNSUPPORTED",
                    "answer_text": build_visualization_guidance(question, prior_cols, prior_rows),
                    "viz": None,
                    "columns": None,
                    "rows": None,
                    "sql": None,
                    "result_object": chart_source,
                    "conversation_state": prior_conversation_state,
                    "normalized_request": normalized_request,
                }
            return {
                "resolved_intent": "viz_no_data",
                "route": "VIZ_NO_DATA",
                "answer_text": build_viz_no_data_answer(prior_route=prior_route, prior_question=prior_question),
                "viz": None,
                "normalized_request": normalized_request,
            }

        if has_active_analysis_context(prior_conversation_state) and intent in {
            "filter_change",
            "follow_up_refinement",
            "comparison_request",
            "topk_modification",
            "sort_modification",
            "filter_removal",
            "grouping_change",
            "correction",
        }:
            log_event(
                logger,
                logging.INFO,
                "graph.context_resolved",
                resolved_intent=intent,
                prior_route=prior_route,
                question_preview=question[:120],
                normalized_request=normalized_request,
            )
            return {
                "question": normalized_request.get("request_text", question),
                "normalized_request": normalized_request,
                "resolved_intent": intent,
            }

        if intent == "new_analytical_question":
            return {
                "question": normalized_request.get("request_text", question),
                "normalized_request": normalized_request,
                "resolved_intent": intent,
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
        schema_text = state.get("schema_text") or get_prompt_schema_text(db_path, question)
        gk = guardrails_agent.evaluate(question)
        memory = _extract_query_memory(question)
        out: AgentState = {
            "schema_text": schema_text,
            "status": gk.status,
            "parsed_intent": gk.parsed_intent or "",
            # Semantic extraction always comes from _extract_query_memory;
            # GatekeeperResult no longer carries these fields.
            "metric": memory["metric"],
            "dimensions": list(memory["dimensions"]),
            "time_range": memory["time_range"],
            "filters": dict(memory["filters"]),
            "sort_by": memory["sort_by"],
            "sort_direction": memory["sort_direction"],
            "aggregation_intent": memory["aggregation_intent"],
            "missing_slots": list(gk.missing_slots or []),
            "clarifying_questions": list(gk.clarifying_questions or []),
        }
        if gk.status == "OUT OF SCOPE":
            parsed_intent = gk.parsed_intent or ""
            out["route"] = "CHAT" if parsed_intent == "greeting" else "OUT_OF_SCOPE"
            out["answer_text"] = build_out_of_scope_answer(parsed_intent, gk.notes or "")
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
            reason=gk.parsed_intent or "",
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
        normalized_request = dict(state.get("normalized_request") or {})
        result_object = build_result_object(
            cols,
            rows,
            sql=state.get("sql", ""),
            question=state.get("question", ""),
            summary_text=formatted["text"],
            context_filters=state.get("filters", {}),
            current_grouping=state.get("dimensions", []),
            time_reference=state.get("time_range", {}),
            entity_focus=state.get("metric", ""),
        )
        answer_text = compose_data_answer(
            question=state.get("question", ""),
            sql=state.get("sql", ""),
            columns=cols,
            rows=rows,
            fallback_text=formatted["text"],
            analysis_agent=analysis_agent,
        )
        change_summary = normalized_request.get("change_summary", "")
        if change_summary:
            answer_text = "{} {}".format(change_summary, answer_text).strip()
        if not rows and state.get("filters"):
            answer_text = "{} The result is empty for {}.".format(
                change_summary or "I applied your request.",
                state.get("filters", {}),
            ).strip()
        if result_object.get("chart_ready"):
            answer_text = with_plot_suggestion(answer_text)
        conversation_state = build_conversation_state(
            question=state.get("question", ""),
            route="DATA",
            sql=state.get("sql", ""),
            result_object=result_object,
            metric=state.get("metric", ""),
            dimensions=state.get("dimensions", []),
            time_range=state.get("time_range", {}),
            filters=state.get("filters", {}),
            sort_by=state.get("sort_by", ""),
            sort_direction=state.get("sort_direction", ""),
            aggregation_intent=state.get("aggregation_intent", ""),
            last_user_intent=state.get("resolved_intent") or state.get("parsed_intent") or "data_query",
            prior_state=state.get("prior_conversation_state", {}),
            normalized_request=normalized_request,
            answer_text=answer_text,
            last_filter_field=normalized_request.get("last_filter_field", ""),
        )
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
            "result_object": result_object,
            "conversation_state": conversation_state,
            "normalized_request": normalized_request,
        }

    # ---- Node: viz_agent ----
    def viz_node(state: AgentState) -> AgentState:
        cols = state.get("columns", [])
        rows = state.get("rows", [])
        result_object = dict(
            state.get("result_object")
            or build_result_object(
                cols,
                rows,
                sql=state.get("sql", ""),
                question=state.get("question", ""),
                context_filters=(state.get("conversation_state") or {}).get("current_filters", {}),
                current_grouping=(state.get("conversation_state") or {}).get("current_grouping", []),
                time_reference=(state.get("conversation_state") or {}).get("current_time_reference", {}),
                entity_focus=(state.get("conversation_state") or {}).get("current_entity_focus", ""),
            )
        )
        conversation_state = dict(state.get("conversation_state") or {})
        normalized_request = dict(state.get("normalized_request") or {})
        if not result_object.get("chart_ready"):
            return {
                "route": "VIZ_UNSUPPORTED",
                "answer_text": build_visualization_guidance(state.get("question", ""), cols, rows),
                "viz": None,
                "columns": None,
                "rows": None,
                "sql": None,
                "result_object": result_object,
                "conversation_state": conversation_state,
                "normalized_request": normalized_request,
            }
        if not supports_visualization_request(state.get("question", ""), cols, rows):
            return {
                "route": "VIZ_UNSUPPORTED",
                "answer_text": build_visualization_guidance(state.get("question", ""), cols, rows),
                "viz": None,
                "columns": None,
                "rows": None,
                "sql": None,
                "result_object": result_object,
                "conversation_state": conversation_state,
                "normalized_request": normalized_request,
            }
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
        if not viz:
            return {
                "route": "VIZ_UNSUPPORTED",
                "answer_text": build_visualization_guidance(state.get("question", ""), cols, rows),
                "viz": None,
                "columns": None,
                "rows": None,
                "sql": None,
                "result_object": result_object,
                "conversation_state": conversation_state,
                "normalized_request": normalized_request,
            }
        chart_label = requested_chart_type(state.get("question", ""))
        if chart_label == "chart":
            chart_label = result_object.get("suggested_chart") or "chart"
        answer_text = "I turned the previous result into a {}.".format(chart_label)
        conversation_state = build_conversation_state(
            question=state.get("question", ""),
            route="VIZ_FOLLOWUP",
            sql=state.get("sql", ""),
            result_object=result_object,
            metric=conversation_state.get("metric", ""),
            dimensions=conversation_state.get("current_grouping", []),
            time_range=conversation_state.get("current_time_reference", {}),
            filters=conversation_state.get("current_filters", {}),
            sort_by=conversation_state.get("sort_by", ""),
            sort_direction=conversation_state.get("sort_direction", ""),
            aggregation_intent=conversation_state.get("aggregation_intent", ""),
            last_user_intent="visualization_request",
            prior_state=conversation_state,
            normalized_request=normalized_request,
            answer_text=answer_text,
            last_filter_field=conversation_state.get("last_filter_field", ""),
        )
        return {
            "viz": viz,
            "answer_text": answer_text,
            "result_object": result_object,
            "conversation_state": conversation_state,
            "normalized_request": normalized_request,
        }

    # ---- Routing functions ----
    def check_context(state: AgentState) -> str:
        intent = state.get("resolved_intent", "new_query")
        route = state.get("route", "")
        if intent == "viz_followup":
            return "viz_direct"
        if intent == "viz_no_data" or route in {"VIZ_NO_DATA", "VIZ_UNSUPPORTED", "CHAT", "CLARIFY"}:
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
            # Short-circuit if the error agent returned an identical SQL to one
            # already attempted — further retries would just repeat the same failure.
            current_sql = (state.get("sql") or "").strip()
            seen_sqls = {
                (a.get("sql") or "").strip()
                for a in state.get("attempts", [])
                if a.get("stage") in {"execution", "validation"}
            }
            if current_sql and current_sql in seen_sqls and repair_count > 0:
                return "end"
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

    prior_result_object = prior.get("result_object")
    if not prior_result_object and (prior.get("columns") or prior.get("preview_rows") or prior.get("rows")):
        prior_result_object = build_result_object(
            prior.get("columns", []),
            prior.get("preview_rows", prior.get("rows", [])),
            sql=prior.get("sql", ""),
            question=prior.get("question", ""),
            context_filters=prior.get("filters", {}),
            current_grouping=prior.get("dimensions", []),
            time_reference=prior.get("time_range", {}),
            entity_focus=prior.get("metric", ""),
        )

    prior_conversation_state = prior.get("conversation_state")
    if not prior_conversation_state:
        prior_conversation_state = build_conversation_state(
            question=prior.get("question", ""),
            route=prior.get("route", ""),
            sql=prior.get("sql", ""),
            result_object=prior_result_object,
            metric=prior.get("metric", ""),
            dimensions=prior.get("dimensions", []),
            time_range=prior.get("time_range", {}),
            filters=prior.get("filters", {}),
            sort_by=prior.get("sort_by", ""),
            sort_direction=prior.get("sort_direction", ""),
            aggregation_intent=prior.get("aggregation_intent", ""),
            last_user_intent=prior.get("resolved_intent") or prior.get("parsed_intent") or "",
        )

    input_state = {
        "question": question,
        "db_path": db_path,
        "route": "",
        "answer_text": "",
        "resolved_intent": "",
        "viz": None,
        "prior_question": prior.get("question", ""),
        "prior_route": prior.get("route", ""),
        "prior_missing_slots": prior.get("missing_slots", []),
        "prior_clarifying_questions": prior.get("clarifying_questions", []),
        "prior_columns": prior.get("columns", []),
        "prior_rows": prior.get("preview_rows", prior.get("rows", [])),
        "prior_sql": prior.get("sql", ""),
        "prior_metric": prior.get("metric", ""),
        "prior_dimensions": prior.get("dimensions", []),
        "prior_time_range": prior.get("time_range", {}),
        "prior_filters": prior.get("filters", {}),
        "prior_sort_by": prior.get("sort_by", ""),
        "prior_sort_direction": prior.get("sort_direction", ""),
        "prior_aggregation_intent": prior.get("aggregation_intent", ""),
        "prior_result_object": prior_result_object or {},
        "prior_conversation_state": prior_conversation_state or {},
    }

    error_message = ""
    try:
        result = graph_app.invoke(input_state, config=config)
        if result is None:
            error_message = PIPELINE_NONE_MESSAGE
            result = {"route": "ERROR", "answer_text": PIPELINE_NONE_MESSAGE}
    except Exception as e:
        error_message = str(e)
        result = {"route": "ERROR", "answer_text": pipeline_error_message(e)}

    if error_message:
        log_event(
            logger,
            logging.ERROR,
            "graph.invoke_failed",
            thread_id=thread_id,
            route=result.get("route", ""),
            prior_route=prior.get("route", ""),
            error=error_message,
        )
    else:
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
