from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.formatters.viz_plotly import requested_chart_type
from app.messages import build_ranking_clarification_message
from app.pipeline.conversation_state import (
    _pick_schema_field,
    build_conversation_state,
    detect_followup_action,
    empty_conversation_state,
)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TOP_K_RE = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)
_LOCATION_RE = re.compile(
    r"\b(?:for|in|only for|just for|filter to|go back to)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"
)
_EXPLAIN_RE = re.compile(
    r"\b(explain( that| this)?|what do you mean|what does this number mean|what did you compare)\b",
    re.IGNORECASE,
)
_SIMPLIFY_RE = re.compile(r"\b(make (it|that) simpler|simplify|simpler)\b", re.IGNORECASE)
_WHY_EMPTY_RE = re.compile(r"\b(why is (that|it) empty|why no result|why is the result empty)\b", re.IGNORECASE)
_RESET_RE = re.compile(r"\b(start over|reset( context)?|clear context)\b", re.IGNORECASE)
_CORRECTION_RE = re.compile(r"^\s*(actually|no[, ]|i meant|rather)\b", re.IGNORECASE)
_COMPARE_RE = re.compile(r"\bcompare\s+(with|to)\b|\b(last year|previous year)\b", re.IGNORECASE)
_GROUP_CHANGE_RE = re.compile(r"\b(by|group by|now by|same thing but by)\s+([a-zA-Z_]+)\b", re.IGNORECASE)
_DATA_HINT_RE = re.compile(
    r"\b(client|clients|transaction|transactions|dossier|dossiers|commune|country|pays|segment|amount|montant)\b",
    re.IGNORECASE,
)
_RANKING_RE = re.compile(r"\b(top|best|worst|highest|lowest)\b", re.IGNORECASE)

_METRIC_PATTERNS = [
    (re.compile(r"\b(client|clients?)\b", re.IGNORECASE), "client_count"),
    (re.compile(r"\b(transaction|transactions?)\b", re.IGNORECASE), "transaction_count"),
    (re.compile(r"\b(dossier|dossiers?)\b", re.IGNORECASE), "dossier_count"),
    (re.compile(r"\b(total amount|montant total|amount|sum|revenue)\b", re.IGNORECASE), "total_amount"),
]

_DIMENSION_PATTERNS = [
    (re.compile(r"\bcommunes?\b", re.IGNORECASE), "commune"),
    (re.compile(r"\b(country|pays)\b", re.IGNORECASE), "country"),
    (re.compile(r"\b(month|mois)\b", re.IGNORECASE), "month"),
    (re.compile(r"\b(year|année|annee)\b", re.IGNORECASE), "year"),
    (re.compile(r"\bsegment\b", re.IGNORECASE), "segment"),
]


def has_active_analysis_context(conversation_state: Dict[str, Any]) -> bool:
    state = conversation_state or {}
    return bool(state.get("last_sql_query") or state.get("last_result_object"))


def classify_turn_intent(question: str, conversation_state: Dict[str, Any], prior_route: str = "") -> str:
    q = (question or "").strip()
    if not q:
        return "unsupported_ambiguous"
    lower = q.lower()
    followup_action = detect_followup_action(q)

    if _RESET_RE.search(lower):
        return "reset_context"
    if _WHY_EMPTY_RE.search(lower):
        return "empty_result_explanation"
    if _SIMPLIFY_RE.search(lower):
        return "simplification_request"
    if _EXPLAIN_RE.search(lower):
        return "explanation_request"
    if followup_action == "chart_request" and (
        has_active_analysis_context(conversation_state)
        or not (_DATA_HINT_RE.search(q) or _YEAR_RE.search(q) or _RANKING_RE.search(q))
    ):
        return "visualization_request"
    if prior_route == "CLARIFY":
        return "clarification_reply"
    if _COMPARE_RE.search(lower):
        return "comparison_request"
    if followup_action == "context_clear":
        return "filter_removal"
    if followup_action in {"topk_modification", "sort_modification", "grouping_change"}:
        return followup_action
    if _CORRECTION_RE.search(q):
        return "correction"
    if followup_action == "filter_refinement":
        return "filter_change" if has_active_analysis_context(conversation_state) else "new_analytical_question"
    if has_active_analysis_context(conversation_state) and len(q.split()) <= 8:
        return "follow_up_refinement"
    if _DATA_HINT_RE.search(q):
        return "new_analytical_question"
    return "unsupported_ambiguous"


def _detect_metric(question: str, fallback: str = "") -> str:
    for pattern, metric in _METRIC_PATTERNS:
        if pattern.search(question or ""):
            return metric
    return fallback


def _detect_dimensions(question: str, fallback: Optional[Sequence[str]] = None) -> List[str]:
    q = question or ""
    dims: List[str] = []
    explicit_groupings = [
        (re.compile(r"\b(by|per|group by|grouped by|now by|same thing but by)\s+communes?\b", re.IGNORECASE), "commune"),
        (re.compile(r"\b(by|per|group by|grouped by|now by|same thing but by)\s+(country|pays)\b", re.IGNORECASE), "country"),
        (re.compile(r"\b(by|per|group by|grouped by|now by|same thing but by)\s+(month|mois)\b", re.IGNORECASE), "month"),
        (re.compile(r"\b(by|per|group by|grouped by|now by|same thing but by)\s+(year|année|annee)\b", re.IGNORECASE), "year"),
        (re.compile(r"\b(by|per|group by|grouped by|now by|same thing but by)\s+segment\b", re.IGNORECASE), "segment"),
        (re.compile(r"\btop\s+\d+\s+communes?\b", re.IGNORECASE), "commune"),
        (re.compile(r"\btop\s+\d+\s+(countries|country|pays)\b", re.IGNORECASE), "country"),
        (re.compile(r"\btop\s+\d+\s+segments?\b", re.IGNORECASE), "segment"),
    ]
    for pattern, dim in explicit_groupings:
        if pattern.search(q):
            dims.append(dim)
    if dims:
        return dims
    return list(fallback or [])


def _detect_limit(question: str, fallback: Optional[int] = None) -> Optional[int]:
    match = _TOP_K_RE.search(question or "")
    if match:
        return int(match.group(1))
    return fallback


def _extract_years(question: str, current_time_reference: Dict[str, Any]) -> List[int]:
    years = [int(match) for match in _YEAR_RE.findall(question or "")]
    if re.search(r"\blast year\b|\bprevious year\b", question or "", re.IGNORECASE):
        current = current_time_reference.get("value")
        if current and str(current).isdigit():
            years.append(int(current) - 1)
    unique: List[int] = []
    for year in years:
        if year not in unique:
            unique.append(year)
    return unique


def _detect_location_value(question: str) -> str:
    match = _LOCATION_RE.search(question or "")
    if match:
        return match.group(1).strip()
    return ""


def _resolve_location_field(question: str, state: Dict[str, Any], schema_text: str) -> str:
    lower = (question or "").lower()
    if "country" in lower or "pays" in lower:
        return _pick_schema_field(schema_text, "country", "country")
    if "commune" in lower:
        return _pick_schema_field(schema_text, "commune", "commune")
    grouping = [str(item).lower() for item in state.get("current_grouping", [])]
    if "commune" in grouping:
        return _pick_schema_field(schema_text, "country", "country")
    if "country" in grouping or "pays" in grouping:
        return _pick_schema_field(schema_text, "commune", "commune")
    return _pick_schema_field(schema_text, "country", "country")


def _normalize_year_filter(years: Sequence[int], existing_time_reference: Dict[str, Any]) -> Dict[str, Any]:
    if years:
        if len(years) == 1:
            return {"kind": "year", "value": str(years[0])}
        return {"kind": "year_set", "value": [str(year) for year in years]}
    return dict(existing_time_reference or {})


def _derive_sort(intent: str, question: str, metric: str, prior_state: Dict[str, Any]) -> Dict[str, str]:
    if intent == "sort_modification":
        if re.search(r"\b(desc|descending)\b", question or "", re.IGNORECASE):
            return {"sort_by": metric or prior_state.get("sort_by", "") or "value", "sort_direction": "desc"}
        return {"sort_by": metric or prior_state.get("sort_by", "") or "value", "sort_direction": "asc"}
    if re.search(r"\btop\b|\bhighest\b|\bbest\b", question or "", re.IGNORECASE):
        return {"sort_by": metric or "value", "sort_direction": "desc"}
    return {
        "sort_by": prior_state.get("sort_by", ""),
        "sort_direction": prior_state.get("sort_direction", ""),
    }


def _clarification_for_request(question: str, metric: str, time_reference: Dict[str, Any]) -> Optional[str]:
    if _RANKING_RE.search(question or ""):
        missing: List[str] = []
        if not metric:
            missing.append("metric")
        if not time_reference:
            missing.append("time_range")
        if missing:
            return build_ranking_clarification_message(missing)
    return None


def _build_change_summary(intent: str, normalized_request: Dict[str, Any], prior_state: Dict[str, Any]) -> str:
    filters = normalized_request.get("filters", {})
    if intent == "comparison_request":
        years = filters.get("year")
        if isinstance(years, list) and len(years) >= 2:
            return "I compared the same topic across {} and {}.".format(years[0], years[-1])
        return "I compared the current topic using the same filters and grouping."
    if intent in {"filter_change", "follow_up_refinement", "correction"}:
        location = normalized_request.get("last_filter_value")
        field = normalized_request.get("last_filter_field", "")
        if location and field:
            return 'Using the same topic as before, I updated the {} filter to "{}".'.format(
                field.replace("_", " "),
                location,
            )
    if intent == "filter_removal":
        field = normalized_request.get("last_filter_field") or prior_state.get("last_filter_field", "filter")
        return "I removed the {} filter and kept the rest of the topic the same.".format(
            str(field).replace("_", " ")
        )
    if intent == "grouping_change":
        dims = normalized_request.get("dimensions", [])
        if dims:
            return "I kept the same topic and regrouped the result by {}.".format(", ".join(dims))
    if intent == "topk_modification":
        limit = normalized_request.get("limit")
        if limit:
            return "I kept the same topic and changed the ranking to top {}.".format(limit)
    if intent == "sort_modification":
        direction = normalized_request.get("sort_direction", "")
        if direction:
            return "I kept the same topic and sorted the result {}.".format(
                "descending" if direction == "desc" else "ascending"
            )
    return ""


def render_normalized_request(normalized_request: Dict[str, Any]) -> str:
    lines = [
        "Normalized analytical request:",
        "- intent: {}".format(normalized_request.get("intent", "")),
        "- original question: {}".format(normalized_request.get("original_question", "")),
    ]
    if normalized_request.get("metric"):
        lines.append("- metric: {}".format(normalized_request["metric"]))
    if normalized_request.get("dimensions"):
        lines.append("- dimensions: {}".format(", ".join(normalized_request["dimensions"])))
    if normalized_request.get("filters"):
        lines.append("- filters: {}".format(normalized_request["filters"]))
    if normalized_request.get("sort_direction") or normalized_request.get("sort_by"):
        lines.append(
            "- sort: {} {}".format(
                normalized_request.get("sort_by") or "value",
                normalized_request.get("sort_direction") or "",
            ).strip()
        )
    if normalized_request.get("limit"):
        lines.append("- limit: {}".format(normalized_request["limit"]))
    if normalized_request.get("comparison_mode"):
        lines.append("- comparison mode: {}".format(normalized_request["comparison_mode"]))
    if normalized_request.get("visualization"):
        lines.append("- visualization: {}".format(normalized_request["visualization"]))
    return "\n".join(lines)


def build_normalized_request(
    question: str,
    intent: str,
    conversation_state: Dict[str, Any],
    schema_text: str,
) -> Dict[str, Any]:
    state = conversation_state or empty_conversation_state()
    start_fresh = intent in {"new_analytical_question", "correction", "clarification_reply"}

    metric = _detect_metric(question, "" if start_fresh else state.get("metric", ""))
    dimensions = _detect_dimensions(question, [] if start_fresh else state.get("current_grouping", []))
    filters = {} if start_fresh else dict(state.get("current_filters", {}) or {})
    time_reference = {} if start_fresh else dict(state.get("current_time_reference", {}) or {})
    limit = _detect_limit(question, None if start_fresh else (state.get("last_normalized_request") or {}).get("limit"))
    sort = _derive_sort(intent, question, metric, state)
    comparison_mode = None
    visualization = None
    last_filter_field = state.get("last_filter_field", "")
    last_filter_value = ""

    years = _extract_years(question, state.get("current_time_reference", {}))
    if years:
        if intent == "comparison_request" and state.get("current_time_reference", {}).get("value"):
            current_year = int(state["current_time_reference"]["value"])
            if current_year not in years:
                years.insert(0, current_year)
        filters["year"] = [str(year) for year in years] if len(years) > 1 else str(years[0])
        time_reference = _normalize_year_filter(years, time_reference)

    if intent in {"filter_change", "follow_up_refinement", "correction"}:
        location = _detect_location_value(question)
        if location:
            field = _resolve_location_field(question, state, schema_text)
            filters[field] = location
            last_filter_field = field
            last_filter_value = location

    if intent == "filter_removal":
        location = _detect_location_value(question)
        if location:
            for key, value in list(filters.items()):
                if value == location:
                    filters.pop(key, None)
                    last_filter_field = key
                    break
        elif state.get("last_filter_field"):
            filters.pop(state["last_filter_field"], None)
            last_filter_field = state["last_filter_field"]

    if intent == "grouping_change":
        dimensions = _detect_dimensions(question, state.get("current_grouping", []))

    if intent == "comparison_request":
        comparison_mode = "year_over_year"
        if "year" not in filters and state.get("current_time_reference", {}).get("value"):
            current_year = int(state["current_time_reference"]["value"])
            compare_years = [current_year - 1, current_year]
            filters["year"] = [str(year) for year in compare_years]
            time_reference = {"kind": "year_set", "value": [str(year) for year in compare_years]}

    if intent == "visualization_request":
        visualization = requested_chart_type(question)

    clarification_message = _clarification_for_request(question, metric, time_reference)
    normalized = {
        "intent": intent,
        "metric": metric,
        "dimensions": dimensions,
        "filters": filters,
        "sort_by": sort["sort_by"],
        "sort_direction": sort["sort_direction"],
        "limit": limit,
        "comparison_mode": comparison_mode,
        "visualization": visualization,
        "needs_clarification": bool(clarification_message),
        "clarification_message": clarification_message,
        "original_question": question,
        "time_reference": time_reference,
        "last_filter_field": last_filter_field,
        "last_filter_value": last_filter_value,
    }
    normalized["change_summary"] = _build_change_summary(intent, normalized, state)
    normalized["request_text"] = render_normalized_request(normalized)
    return normalized


def _filters_to_text(filters: Dict[str, Any]) -> str:
    if not filters:
        return "no extra filters"
    parts = []
    for key, value in filters.items():
        parts.append("{}={}".format(str(key).replace("_", " "), value))
    return ", ".join(parts)


def build_direct_assistant_response(
    question: str,
    intent: str,
    conversation_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    state = dict(conversation_state or empty_conversation_state())
    if intent == "unsupported_ambiguous":
        return None

    last_result = dict(state.get("last_result_object") or {})
    metric = state.get("metric", "")
    grouping = state.get("current_grouping", [])
    filters = state.get("current_filters", {})

    if intent == "reset_context":
        cleared_state = empty_conversation_state()
        cleared_state["history"] = list(state.get("history", []))[-20:]
        return {
            "route": "CHAT",
            "answer_text": "I cleared the current analysis context. Ask a new data question when you're ready.",
            "conversation_state": cleared_state,
            "result_object": {},
        }

    if intent == "simplification_request":
        explanation = state.get("last_explanation") or last_result.get("summary_text") or ""
        if not explanation:
            return {
                "route": "CHAT",
                "answer_text": "I can simplify the last answer once we have a result to talk about.",
                "conversation_state": state,
                "result_object": last_result,
            }
        answer = "In simple terms: {}".format(explanation.split(".")[0].strip().rstrip(".") + ".")
        return {
            "route": "CHAT",
            "answer_text": answer,
            "conversation_state": build_conversation_state(
                question=question,
                route="CHAT",
                sql=state.get("last_sql_query", ""),
                result_object=last_result,
                metric=metric,
                dimensions=grouping,
                time_range=state.get("current_time_reference", {}),
                filters=filters,
                sort_by=state.get("sort_by", ""),
                sort_direction=state.get("sort_direction", ""),
                aggregation_intent=state.get("aggregation_intent", ""),
                last_user_intent=intent,
                prior_state=state,
                normalized_request=state.get("last_normalized_request", {}),
                answer_text=answer,
                last_filter_field=state.get("last_filter_field", ""),
            ),
            "result_object": last_result,
        }

    if intent == "empty_result_explanation":
        if int(last_result.get("row_count", 0) or 0) > 0:
            answer = "The last result is not empty. It returned {} rows.".format(last_result.get("row_count", 0))
        else:
            answer = (
                "The last query returned no rows for {}. "
                "That usually means the filter combination is too restrictive or there is no matching data."
            ).format(_filters_to_text(filters))
        return {
            "route": "CHAT",
            "answer_text": answer,
            "conversation_state": build_conversation_state(
                question=question,
                route="CHAT",
                sql=state.get("last_sql_query", ""),
                result_object=last_result,
                metric=metric,
                dimensions=grouping,
                time_range=state.get("current_time_reference", {}),
                filters=filters,
                sort_by=state.get("sort_by", ""),
                sort_direction=state.get("sort_direction", ""),
                aggregation_intent=state.get("aggregation_intent", ""),
                last_user_intent=intent,
                prior_state=state,
                normalized_request=state.get("last_normalized_request", {}),
                answer_text=answer,
                last_filter_field=state.get("last_filter_field", ""),
            ),
            "result_object": last_result,
        }

    if intent == "explanation_request":
        if not state.get("last_explanation") and not last_result:
            return {
                "route": "CHAT",
                "answer_text": "I can explain the last result once we have one.",
                "conversation_state": state,
                "result_object": last_result,
            }
        if re.search(r"\bwhat did you compare\b", question or "", re.IGNORECASE):
            request = state.get("last_normalized_request", {})
            answer = "I compared {} with {} using {} and {}.".format(
                request.get("metric", metric or "the same metric"),
                request.get("filters", {}).get("year", state.get("current_time_reference", {}).get("value", "the requested period")),
                ", ".join(grouping) if grouping else "the same grouping",
                _filters_to_text(filters),
            )
        elif re.search(r"\bwhat does this number mean\b", question or "", re.IGNORECASE):
            answer = "That number is the {} for {} with {}.".format(
                metric.replace("_", " ") if metric else "result",
                ", ".join(grouping) if grouping else "the current topic",
                _filters_to_text(filters),
            )
        else:
            answer = "Here is what I mean: {}".format(
                state.get("last_explanation") or last_result.get("summary_text") or "the result follows the current topic."
            )
        return {
            "route": "CHAT",
            "answer_text": answer,
            "conversation_state": build_conversation_state(
                question=question,
                route="CHAT",
                sql=state.get("last_sql_query", ""),
                result_object=last_result,
                metric=metric,
                dimensions=grouping,
                time_range=state.get("current_time_reference", {}),
                filters=filters,
                sort_by=state.get("sort_by", ""),
                sort_direction=state.get("sort_direction", ""),
                aggregation_intent=state.get("aggregation_intent", ""),
                last_user_intent=intent,
                prior_state=state,
                normalized_request=state.get("last_normalized_request", {}),
                answer_text=answer,
                last_filter_field=state.get("last_filter_field", ""),
            ),
            "result_object": last_result,
        }

    return None
