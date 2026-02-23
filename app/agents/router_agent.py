import re 
from dataclasses import dataclass
from typing import Literal,Optional

Route = Literal["REFUSE","CLARIFY","DATA","CHAT"]

@dataclass
class RouterDecision:
    route: Route
    reason : str
    clarifying_question : Optional[str] = None


# Define patern 

DATA_HINTS = [
    r"\bclients?\b",
    r"\bdossiers?\b",
    r"\btransactions?\b",
    r"\bmontant\b",
    r"\bsegment\b",
    r"\bcommune\b",
    r"\benseigne\b",
    r"\bcategorie_achat\b",
    r"\btaux\b",
    r"\bsolde\b",
    r"\bincident\b"
]

RANKING_PATTERN = r"\b(top|best|worst|highest|lowest|meilleur|pire)\b"
METRIC_HINTS = r"\b(montant|total|sum|count|nombre|avg|average|moyenne|max|min|spend|dépense|transactions?|dossiers?)\b"
TIME_HINTS = r"\b(20\d{2}|mois|month|année|year|entre|from|to|depuis|avant|après)\b"


# Destructive 
REFUSE_PATTERN = r"\b(DELETE|DROP|UPDATE|INSERT|ALTER|ATTACH|DETACH|PRAGMA|CREATE|REPLACE|COPY|TRUNCATE)\b"
INJECTION_PATTERN = r"(;|--|/\*|\*/)"


def _contain_any(patterns: list[str],text :str) -> bool:
    return any(re.search(p,text,flags= re.IGNORECASE) for p in patterns)

def route_message(message: str) -> RouterDecision:
    q = (message or "").strip()
    # Refuse if destructive intent or SQL injection markers
    if not q : 
        return RouterDecision(route="REFUSE", reason="destructive_or_injection")
    # Clarify if ranking request but missing metric
    if re.search(RANKING_PATTERN,q, flags=re.IGNORECASE): 
        need_metric = not re.search(METRIC_HINTS, q ,flags= re.IGNORECASE)
        need_time = not re.search(TIME_HINTS, q, flags= re.IGNORECASE)
        if need_metric or need_time:
            missing = []
            if need_metric:
                missing.append("metric")
            if need_time: 
                missing.append("time_range")
            cq_parts = []
            if need_metric:
                cq_parts.append("Which metric for 'top/best'? (total amount, #transactions, #dossiers, etc.)")  
            if need_time:
                cq_parts.append("Which time period?(eg. 2024, 2025 or specific dates)")
            return RouterDecision(
                route= "CLARIFY",
                reason= f"ranking_missing_{'_'.join(missing)}",
                clarifying_question= " ".join(cq_parts)
            )
    if _contain_any(DATA_HINTS,q):
        return RouterDecision(route="DATA", reason="mention_data_entities")
    return RouterDecision(route="CHAT", reason= "no_data_signals")