from __future__ import annotations 
import re
from typing import Tuple

# Keywords to block

BLOCKED_KEYWORDS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "ATTACH", "DETACH",
    "PRAGMA", "COPY", "CREATE", "REPLACE"}


PII_COLUMNS = {"nom", "prenom","date_naissance"}

SELECT_START_RE = re.compile(r"^\s*SELECT\b",re.IGNORECASE)
def validate_sql(sql:str) -> Tuple[bool,str]:
    s = (sql or "").strip()
    if not s: 
        return False, "Empty SQL."
    # Must start with Select
    if not SELECT_START_RE.match(s):
        return False, "Only SELECT queries are allowed."
    # Block multiple statements
    if ";" in s: 
        return False, "Multiple statements are not allowed."
    
    # Tokenize completion
    upper = re.sub(r"[ˆA-Za-z0-9_]+", " ",s).upper().split()
    for kw in BLOCKED_KEYWORDS:
        if kw in upper:
            return False, f"Blocked keyword:{kw}"
    
    lower = s.lower()
    for col in PII_COLUMNS:
        # block selecting those cols anywhere
        if re.search(rf"\b{re.escape(col)}\b",lower):
            return False, f"PII column not allowed:{col}"
    
    return True, "OKAY"