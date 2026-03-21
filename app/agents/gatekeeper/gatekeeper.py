import re

from app.agents.gatekeeper.schemas import GatekeeperResult

FORBIDDEN_INPUT_PATTERNS = [
    r";", r"--", r"/\*", r"\*/",
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
    r"\bALTER\b", r"\bATTACH\b", r"\bDETACH\b", r"\bPRAGMA\b",
    r"\bCREATE\b", r"\bREPLACE\b", r"\bCOPY\b",
]

SQL_LIKE_START = r"^\s*(SELECT|UPDATE|DELETE|INSERT|DROP|ALTER|PRAGMA|ATTACH|CREATE|REPLACE|COPY)\b"
PII_PATTERN = r"\b(nom|prenom|date_naissance)\b"


def is_unsafe_user_input(q: str) -> bool:
    q = q or ""
    if re.search(SQL_LIKE_START, q, flags=re.IGNORECASE):
        return True
    for p in FORBIDDEN_INPUT_PATTERNS:
        if re.search(p, q, flags=re.IGNORECASE):
            return True
    return False


def gatekeep(user_question: str) -> GatekeeperResult:
    q = user_question or ""

    # 1) Block SQL
    if is_unsafe_user_input(q):
        return GatekeeperResult(
            status="OUT OF SCOPE",
            parsed_intent="unsafe_sql_or_injection",
            clarifying_questions=[],
            missing_slots=[],
            notes="User input contains SQL/injection or destructive intent. Refused before SQL generation."
        )

    # 2) Block PII
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
