from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.formatters.viz_plotly import describe_result_set

_SCHEMA_TABLE_RE = re.compile(r"TABLE\s+\w+\((.*?)\)", re.IGNORECASE | re.DOTALL)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TOP_K_RE = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
_GROUPING_RE = re.compile(r"\bby\s+([a-zA-Z_]+)\b", re.IGNORECASE)
_LOCATION_RE = re.compile(
    r"\b(?:for|in|only for|just for|filter to)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b",
)
_CLEAR_FILTER_RE = re.compile(
    r"\b(?:forget|ignore|remove|without)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b",
    re.IGNORECASE,
)

SEMANTIC_FIELD_CANDIDATES = {
    "country": ("pays", "country", "nation"),
    "commune": ("commune", "city", "town"),
    "year": ("year", "annee", "annee_transaction", "annee_dossier", "date", "date_transaction"),
    "month": ("month", "mois"),
    "segment": ("segment", "segment_client"),
    "client_count": ("nombre_clients", "count", "count_clients", "nb_clients"),
}

GROUPING_ALIASES = {
    "country": "country",
    "pays": "country",
    "commune": "commune",
    "city": "commune",
    "month": "month",
    "mois": "month",
    "year": "year",
    "annee": "year",
    "segment": "segment",
    "segment_client": "segment",
}

VIZ_REQUEST_RE = re.compile(
    r"\b(plot|chart|graph|visuali[sz]e|show\s+(me\s+)?(a\s+)?(chart|graph|plot)|draw|bar\s*chart|pie\s*chart|line\s*chart)\b",
    re.IGNORECASE,
)


def extract_schema_columns(schema_text: str) -> List[str]:
    fields: List[str] = []
    seen = set()
    for match in _SCHEMA_TABLE_RE.finditer(schema_text or ""):
        for part in match.group(1).split(","):
            name = part.strip().split()[0] if part.strip() else ""
            if name and name.lower() not in seen:
                seen.add(name.lower())
                fields.append(name)
    return fields


def _pick_schema_field(schema_text: str, concept: str, fallback: str = "") -> str:
    columns = extract_schema_columns(schema_text)
    lowered = {col.lower(): col for col in columns}
    for candidate in SEMANTIC_FIELD_CANDIDATES.get(concept, ()):
        if candidate in lowered:
            return lowered[candidate]
    return fallback


def _normalize_grouping_name(value: str) -> str:
    token = (value or "").strip().lower()
    return GROUPING_ALIASES.get(token, token)


def _derive_entity_focus(metric: str, grouping: Sequence[str]) -> str:
    if metric:
        return metric
    if grouping:
        return grouping[0]
    return ""


def _build_topic_label(metric: str, grouping: Sequence[str]) -> str:
    metric_text = (metric or "").replace("_", " ").strip()
    grouping_text = ", ".join(grouping or [])
    if metric_text and grouping_text:
        return "{} by {}".format(metric_text, grouping_text)
    return metric_text or grouping_text


def empty_conversation_state() -> Dict[str, Any]:
    return {
        "active_topic": "",
        "last_user_intent": "",
        "last_user_question": "",
        "last_route": "",
        "last_sql_query": "",
        "last_result_object": {},
        "last_chartable_result": {},
        "last_explanation": "",
        "last_normalized_request": {},
        "current_filters": {},
        "current_grouping": [],
        "current_time_reference": {},
        "current_entity_focus": "",
        "metric": "",
        "sort_by": "",
        "sort_direction": "",
        "aggregation_intent": "",
        "current_turn_type": "",
        "last_filter_field": "",
        "history": [],
    }


def build_result_object(
    columns: Sequence[str],
    rows: Any,
    *,
    sql: str = "",
    question: str = "",
    summary_text: str = "",
    context_filters: Optional[Dict[str, Any]] = None,
    current_grouping: Optional[Sequence[str]] = None,
    time_reference: Optional[Dict[str, Any]] = None,
    entity_focus: str = "",
) -> Dict[str, Any]:
    profile = describe_result_set(columns, rows)
    return {
        "question": question,
        "sql": sql,
        "columns": [str(c) for c in (columns or [])],
        "rows": rows if isinstance(rows, list) else [],
        "row_count": len(rows or []),
        "semantic_type": profile["semantic_type"],
        "chart_ready": profile["chart_ready"],
        "suggested_chart": profile["suggested_chart"],
        "x_column": profile["x_column"],
        "y_column": profile["y_column"],
        "context_filters": dict(context_filters or {}),
        "current_grouping": list(current_grouping or []),
        "time_reference": dict(time_reference or {}),
        "entity_focus": entity_focus,
        "category_count": profile["category_count"],
        "chart_reason": profile["reason"],
        "summary_text": summary_text,
    }


def build_conversation_state(
    *,
    question: str,
    route: str,
    sql: str,
    result_object: Optional[Dict[str, Any]],
    metric: str,
    dimensions: Sequence[str],
    time_range: Optional[Dict[str, Any]],
    filters: Optional[Dict[str, Any]],
    sort_by: str,
    sort_direction: str,
    aggregation_intent: str,
    last_user_intent: str,
    prior_state: Optional[Dict[str, Any]] = None,
    normalized_request: Optional[Dict[str, Any]] = None,
    answer_text: str = "",
    last_filter_field: str = "",
) -> Dict[str, Any]:
    base = dict(prior_state or empty_conversation_state())
    grouping = list(dimensions or [])
    result_object = dict(result_object or {})
    topic = _build_topic_label(metric, grouping)
    history = list(base.get("history", []))
    history.append(
        {
            "user_question": question,
            "intent": last_user_intent,
            "route": route,
            "sql": sql,
            "row_count": result_object.get("row_count", 0),
            "filters": dict(filters or result_object.get("context_filters") or {}),
            "grouping": grouping or list(result_object.get("current_grouping") or []),
        }
    )
    history = history[-20:]
    last_chartable_result = (
        result_object if result_object.get("chart_ready") else dict(base.get("last_chartable_result") or {})
    )
    return {
        "active_topic": topic or base.get("active_topic", ""),
        "last_user_intent": last_user_intent,
        "last_user_question": question,
        "last_route": route,
        "last_sql_query": sql,
        "last_result_object": result_object,
        "last_chartable_result": last_chartable_result,
        "last_explanation": answer_text or base.get("last_explanation", ""),
        "last_normalized_request": dict(normalized_request or base.get("last_normalized_request") or {}),
        "current_filters": dict(filters or result_object.get("context_filters") or {}),
        "current_grouping": grouping or list(result_object.get("current_grouping") or []),
        "current_time_reference": dict(time_range or result_object.get("time_reference") or {}),
        "current_entity_focus": _derive_entity_focus(metric, grouping),
        "metric": metric,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "aggregation_intent": aggregation_intent,
        "current_turn_type": last_user_intent,
        "last_filter_field": last_filter_field or base.get("last_filter_field", ""),
        "history": history,
    }


def render_conversation_state(state: Dict[str, Any]) -> str:
    lines: List[str] = []
    if state.get("metric"):
        lines.append("- metric: {}".format(state.get("metric")))
    if state.get("current_grouping"):
        lines.append("- grouping: {}".format(", ".join(state.get("current_grouping", []))))
    if state.get("current_time_reference"):
        lines.append(
            "- time reference: {}".format(
                json.dumps(state.get("current_time_reference", {}), ensure_ascii=False, sort_keys=True)
            )
        )
    if state.get("current_filters"):
        lines.append(
            "- filters: {}".format(
                json.dumps(state.get("current_filters", {}), ensure_ascii=False, sort_keys=True)
            )
        )
    if state.get("sort_by") or state.get("sort_direction"):
        lines.append(
            "- sort: {} {}".format(
                state.get("sort_by") or "value",
                state.get("sort_direction") or "",
            ).strip()
        )
    if state.get("aggregation_intent"):
        lines.append("- aggregation intent: {}".format(state.get("aggregation_intent")))
    result_object = state.get("last_result_object") or {}
    if result_object.get("semantic_type"):
        lines.append("- last result type: {}".format(result_object.get("semantic_type")))
    if result_object.get("suggested_chart"):
        lines.append("- suggested chart: {}".format(result_object.get("suggested_chart")))
    return "\n".join(lines)


def detect_followup_action(question: str) -> str:
    q = (question or "").strip()
    if not q:
        return "new_query"
    lower = q.lower()
    if re.search(r"\b(clear|reset)\s+(the\s+)?context\b|\bstart over\b", lower):
        return "context_reset"
    if _CLEAR_FILTER_RE.search(q):
        return "context_clear"
    if re.search(r"\bcompare\s+(with|to)\b", lower):
        return "time_comparison"
    if _TOP_K_RE.search(q):
        return "topk_modification"
    if re.search(r"\b(sort|order)\b", lower) or re.search(r"\b(desc|descending|asc|ascending)\b", lower):
        return "sort_modification"
    if _GROUPING_RE.search(q) and re.search(r"\b(now|instead|group|break down|plot)\b", lower):
        return "grouping_change"
    if VIZ_REQUEST_RE.search(q):
        return "chart_request"
    if re.search(r"^\s*(and|only|just)\b", lower) or _LOCATION_RE.search(q):
        return "filter_refinement"
    return "new_query"


def _extract_filter_value(question: str) -> str:
    clear_match = _CLEAR_FILTER_RE.search(question or "")
    if clear_match:
        return clear_match.group(1).strip()
    location_match = _LOCATION_RE.search(question or "")
    if location_match:
        return location_match.group(1).strip()
    return ""


def _resolve_filter_field(question: str, conversation_state: Dict[str, Any], schema_text: str) -> str:
    q = (question or "").lower()
    if "country" in q or "pays" in q:
        return _pick_schema_field(schema_text, "country", "country")
    if "commune" in q or "city" in q or "town" in q:
        return _pick_schema_field(schema_text, "commune", "commune")

    grouping = [_normalize_grouping_name(item) for item in conversation_state.get("current_grouping", [])]
    if "commune" in grouping:
        preferred = _pick_schema_field(schema_text, "country")
        return preferred or "country"
    if "country" in grouping:
        preferred = _pick_schema_field(schema_text, "commune")
        return preferred or "commune"

    return _pick_schema_field(schema_text, "country", "country")


def _resolve_grouping_field(question: str, schema_text: str) -> str:
    match = _GROUPING_RE.search(question or "")
    if not match:
        return ""
    token = _normalize_grouping_name(match.group(1))
    if token == "country":
        return _pick_schema_field(schema_text, "country", "country")
    if token == "commune":
        return _pick_schema_field(schema_text, "commune", "commune")
    if token == "month":
        return _pick_schema_field(schema_text, "month", "month")
    if token == "year":
        return _pick_schema_field(schema_text, "year", "year")
    if token == "segment":
        return _pick_schema_field(schema_text, "segment", "segment")
    return token


def should_reuse_result_for_chart(question: str, conversation_state: Dict[str, Any]) -> bool:
    if detect_followup_action(question) != "chart_request":
        return False
    requested_grouping = _resolve_grouping_field(question, "")
    current_grouping = conversation_state.get("current_grouping", [])
    if requested_grouping and requested_grouping not in current_grouping:
        return False
    return True


def build_followup_question(
    prior_question: str,
    followup_question: str,
    conversation_state: Dict[str, Any],
    schema_text: str,
) -> str:
    action = detect_followup_action(followup_question)
    state_text = render_conversation_state(conversation_state)
    prefix = "Previous request:\n{}\n\nStructured context:\n{}\n\n".format(
        prior_question.strip(),
        state_text or "- none",
    )

    if action == "filter_refinement":
        value = _extract_filter_value(followup_question)
        field = _resolve_filter_field(followup_question, conversation_state, schema_text)
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: filter refinement\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + '- add or replace the filter {} = "{}"\n'.format(field, value or followup_question.strip())
            + "- keep the current metric, grouping, and time reference unless the user changed them.\n"
            + "Return the updated analytics request."
        )

    if action == "context_clear":
        value = _extract_filter_value(followup_question)
        field = _resolve_filter_field(followup_question, conversation_state, schema_text)
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: filter removal\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + '- remove the filter {} = "{}" if it is currently active\n'.format(field, value or "")
            + "- keep the current metric, grouping, and time reference.\n"
            + "Return the updated analytics request."
        )

    if action == "time_comparison":
        year_match = _YEAR_RE.search(followup_question or "")
        compare_year = year_match.group(1) if year_match else ""
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: time comparison\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + "- compare the current request against {}\n".format(compare_year or "the requested comparison period")
            + "- keep the current filters, grouping, and metric.\n"
            + "Return the updated analytics request."
        )

    if action == "topk_modification":
        top_k_match = _TOP_K_RE.search(followup_question or "")
        top_k = top_k_match.group(1) if top_k_match else ""
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: ranking modification\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + "- change the ranking limit to top {}\n".format(top_k or "requested value")
            + "- keep the current metric, filters, grouping, and time reference.\n"
            + "Return the updated analytics request."
        )

    if action == "sort_modification":
        direction = "descending" if re.search(r"\b(desc|descending)\b", followup_question or "", re.IGNORECASE) else "ascending"
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: sort modification\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + "- sort the result {}\n".format(direction)
            + "- keep the current metric, filters, grouping, and time reference.\n"
            + "Return the updated analytics request."
        )

    if action == "grouping_change":
        grouping_field = _resolve_grouping_field(followup_question, schema_text) or "requested grouping"
        return (
            prefix
            + "Apply this follow-up update:\n"
            + "- type: grouping change\n"
            + "- user follow-up: {}\n".format(followup_question.strip())
            + "- regroup the analysis by {}\n".format(grouping_field)
            + "- keep the current metric, filters, and time reference.\n"
            + "Return the updated analytics request."
        )

    return (
        prefix
        + "Apply this follow-up change:\n{}\n\nReturn the updated analytics request.".format(
            followup_question.strip()
        )
    )
