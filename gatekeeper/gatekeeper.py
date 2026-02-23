import json
import re

from gatekeeper.schemas import GatekeeperResult
from gatekeeper.rules import REQUIRED_SLOTS_BY_INTENT
from gatekeeper.prompts import GATEKEEPER_SYSTEM
from app.llm.factory import get_llm

FORBIDDEN_INPUT_PATTERNS = [
    r";", r"--", r"/\*", r"\*/",
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
    r"\bALTER\b", r"\bATTACH\b", r"\bDETACH\b", r"\bPRAGMA\b",
    r"\bCREATE\b", r"\bREPLACE\b", r"\bCOPY\b",
]

SQL_LIKE_START = r"^\s*(SELECT|UPDATE|DELETE|INSERT|DROP|ALTER|PRAGMA|ATTACH|CREATE|REPLACE|COPY)\b"
PII_PATTERN = r"\b(nom|prenom|date_naissance)\b"

def is_unsafe_user_input(q: str) -> bool:
    if re.search(SQL_LIKE_START, q, flags=re.IGNORECASE):
        return True
    for p in FORBIDDEN_INPUT_PATTERNS:
        if re.search(p, q, flags=re.IGNORECASE):
            return True
    return False


def call_llm(messages: list[dict]) -> str:
    llm = get_llm()
    lc_messages = []
    for m in messages: 
        lc_messages.append(m["role"], m["content"])
    resp = llm.invoke(lc_messages)
    return resp.content if hasattr(resp, "content") else str(resp)


def apply_rule_checks(res: GatekeeperResult) -> GatekeeperResult:
    intent = res.parsed_intent or ""
    required = REQUIRED_SLOTS_BY_INTENT.get(intent, [])

    missing = []
    for slot in required:
        if getattr(res, slot, None) in (None, "", [], {}):
            if slot not in missing:
                missing.append(slot)

    if missing:
        res.status = "NEEDS CLARIFICATION"
        res.missing_slots = sorted(set(res.missing_slots + missing))

        if not res.clarifying_questions:
            qs = []
            if "time_range" in missing:
                qs.append("Which period do you want? (a) all of 2025 (b) a certain period (give dates)")
            if "metric" in missing:
                qs.append("Which metric do you want?")
            res.clarifying_questions = qs

    return res



def gatekeep(user_question: str) -> GatekeeperResult:
    q = user_question or ""

    # 1) Block SQL / injection
    if is_unsafe_user_input(q):
        return GatekeeperResult(
            status="OUT OF SCOPE",
            parsed_intent="unsafe_sql_or_injection",
            clarifying_questions=[],
            missing_slots=[],
            notes="User input contains SQL/injection or destructive intent. Refused before SQL generation."
        )

    # 2) Block PII(Personally Identifiable Information) requests (user asks for nom/prenom/date_naissance)
    if re.search(PII_PATTERN, q, flags=re.IGNORECASE):
        return GatekeeperResult(
            status="OUT OF SCOPE",
            parsed_intent="pii_request",
            clarifying_questions=[],
            missing_slots=[],
            notes="PII request detected (nom/prenom/date_naissance). Refused before SQL generation."
        )

    # 3) Otherwise allow SQL generation
    return GatekeeperResult(
        status="READY_FOR_SQL",
        parsed_intent="sql_query",
        clarifying_questions=[],
        missing_slots=[],
        notes="Allowed to generate SQL."
    )