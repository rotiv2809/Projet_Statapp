"""Shared constants used across multiple modules."""

from __future__ import annotations

import re

PII_COLUMNS: set[str] = {"nom", "prenom", "date_naissance"}

CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    if not text:
        return ""
    return re.sub(CODE_FENCE_RE, "", text).strip()


def clean_sql(text: str) -> str:
    """Strip code fences, trailing blank lines, and semicolons from raw SQL."""
    if not text:
        return ""
    s = strip_code_fences(text)
    lines = []
    for line in s.splitlines():
        if not line.strip() and lines:
            break
        lines.append(line)
    s = "\n".join(lines).strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s
