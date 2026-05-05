"""
Lightweight semantic router for user intent classification.

Connection in flow:
- Upstream: called by app/agents/guardrails/agent.py after hard safety passes.
- This file: classifies message as REFUSE, CLARIFY, DATA, or CHAT.
- Downstream: GuardrailsAgent converts RouterDecision into GatekeeperResult.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from app.agents.guardrails.gatekeeper import is_unsafe_user_input
from app.messages import TIME_RANGE_CLARIFICATION_MESSAGE, build_ranking_clarification_message

Route = Literal["REFUSE", "CLARIFY", "DATA", "CHAT"]


@dataclass
class RouterDecision:
    route: Route
    reason: str
    clarifying_question: Optional[str] = None


DATA_HINTS = [
    # Core entity names
    r"\bclients?\b",
    r"\bcustomers?\b",
    r"\bdossiers?\b",
    r"\btransactions?\b",
    r"\bpayments?\b",
    # Metrics / amounts
    r"\bmontant\b",
    r"\bamounts?\b",
    r"\bspending?\b",
    r"\brevenue\b",
    r"\bsum\b",
    r"\baverage\b",
    r"\bmoyenne\b",
    # Dimensions
    r"\bsegment\b",
    r"\bcommunes?\b",
    r"\bcities?\b",
    r"\bcountry\b",
    r"\bpays\b",
    r"\benseigne\b",
    r"\bcategorie_achat\b",
    r"\bcategories?\b",
    r"\bchannel\b",
    r"\bcanal\b",
    # KPIs
    r"\btaux\b",
    r"\brates?\b",
    r"\bratios?\b",
    r"\bsolde\b",
    r"\bbalance\b",
    r"\bincidents?\b",
    r"\bacceptance\b",
    # Time signals
    r"\b20\d{2}\b",
    r"\bmonthly?\b",
    r"\bmois\b",
    r"\byearly?\b",
    r"\bannee\b",
]

RANKING_PATTERN = r"\b(top|best|worst|highest|lowest|meilleur|pire)\b"
METRIC_HINTS = r"\b(montant|total|sum|count|nombre|avg|average|moyenne|max|min|spend|dépense|transactions?|dossiers?|clients?)\b"
TIME_HINTS = r"\b(20\d{2}|mois|month|année|year|entre|from|to|depuis|avant|après)\b"
# Entities that are inherently time-scoped (financial/activity data grows over time)
TEMPORAL_ENTITY_HINTS = r"\b(transactions?|dossiers?|payments?|montant|amounts?|spending|revenue|paiements?)\b"
# Signals that the user wants an aggregate rather than a structural schema question
AGGREGATE_HINTS = r"\b(total|sum|how many|nombre|combien|average|avg|moyenne|count)\b"
GREETING_WORDS = {
    "hello",
    "hi",
    "hey",
    "bonjour",
    "salut",
    "yo",
    "goodmorning",
    "goodevening",
}


def _contain_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _is_greeting_message(text: str) -> bool:
    cleaned = re.sub(r"[^a-zA-Z]", " ", (text or "").lower())
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return False
    if len(tokens) > 4:
        return False
    return all(t in GREETING_WORDS for t in tokens)


def route_message(message: str) -> RouterDecision:
    q = (message or "").strip()
    if not q:
        return RouterDecision(route="REFUSE", reason="empty_message")

    if is_unsafe_user_input(q):
        return RouterDecision(route="REFUSE", reason="unsafe_sql_or_injection")

    if _is_greeting_message(q):
        return RouterDecision(route="CHAT", reason="greeting")

    if re.search(RANKING_PATTERN, q, flags=re.IGNORECASE):
        need_metric = not re.search(METRIC_HINTS, q, flags=re.IGNORECASE)
        need_time = not re.search(TIME_HINTS, q, flags=re.IGNORECASE)
        if need_metric or need_time:
            missing = []
            if need_metric:
                missing.append("metric")
            if need_time:
                missing.append("time_range")

            cq_text = build_ranking_clarification_message(missing)

            return RouterDecision(
                route="CLARIFY",
                reason=f"ranking_missing_{'_'.join(missing)}",
                clarifying_question=cq_text,
            )
        return RouterDecision(route="DATA", reason="ranking_complete")

    # Ask for a time range when the query aggregates inherently time-scoped data
    # (transactions, dossiers, amounts) but gives no temporal anchor at all.
    # This catches "how many transactions?" or "total montant?" without a period.
    # Multi-turn follow-ups are exempt because context_resolver injects the prior
    # time reference into the question text before guardrails runs.
    if (
        re.search(TEMPORAL_ENTITY_HINTS, q, flags=re.IGNORECASE)
        and re.search(AGGREGATE_HINTS, q, flags=re.IGNORECASE)
        and not re.search(TIME_HINTS, q, flags=re.IGNORECASE)
    ):
        return RouterDecision(
            route="CLARIFY",
            reason="temporal_query_missing_time_range",
            clarifying_question=TIME_RANGE_CLARIFICATION_MESSAGE,
        )

    if _contain_any(DATA_HINTS, q):
        return RouterDecision(route="DATA", reason="mention_data_entities")

    return RouterDecision(route="CHAT", reason="no_data_signals")
