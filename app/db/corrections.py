"""Expert correction logging and retrieval."""

from __future__ import annotations

import re
import sqlite3
from difflib import SequenceMatcher
from typing import Optional

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_CORRECTION_MATCH_THRESHOLD = 0.55  # minimum similarity score to reuse a correction


def _normalize_question(question: str) -> str:
    return " ".join((question or "").strip().lower().split())


def _tokenize_question(question: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(question or "") if len(t) > 2}


def _similarity(a: str, b: str) -> float:
    """Combined token-overlap + sequence-ratio similarity in [0, 1]."""
    tokens_a = _tokenize_question(a)
    tokens_b = _tokenize_question(b)
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))
    ratio = SequenceMatcher(None, _normalize_question(a), _normalize_question(b)).ratio()
    return overlap * 0.6 + ratio * 0.4


def _ensure_corrections_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS corrections_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            normalized_question TEXT,
            generated_sql TEXT NOT NULL,
            corrected_sql TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(corrections_log)")
    columns = {row[1] for row in cur.fetchall()}
    if "normalized_question" not in columns:
        cur.execute("ALTER TABLE corrections_log ADD COLUMN normalized_question TEXT")
        cur.execute(
            "UPDATE corrections_log SET normalized_question = LOWER(TRIM(question)) WHERE normalized_question IS NULL"
        )


def log_correction(db_path: str, question: str, generated_sql: str, corrected_sql: str, user: str = "expert") -> None:
    """Log an expert correction to the corrections_log table."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        _ensure_corrections_table(cur)
        cur.execute(
            """
            INSERT INTO corrections_log (question, normalized_question, generated_sql, corrected_sql, user)
            VALUES (?, ?, ?, ?, ?)
            """,
            (question, _normalize_question(question), generated_sql, corrected_sql, user),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_similar_correction(db_path: str, question: str) -> Optional[str]:
    """Fetch a corrected SQL for a similar question, if available.

    Strategy (in priority order):
    1. Exact normalized-string match (fastest).
    2. Fuzzy similarity match — scores all corrections and picks the best one
       above _CORRECTION_MATCH_THRESHOLD, so rephrased questions also benefit
       from expert memory.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        _ensure_corrections_table(cur)
        normalized_question = _normalize_question(question)

        # 1. Exact match
        cur.execute(
            """
            SELECT corrected_sql
            FROM corrections_log
            WHERE normalized_question = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (normalized_question,),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        # 2. Fuzzy match — fetch all corrections and score in Python
        cur.execute(
            """
            SELECT question, corrected_sql
            FROM corrections_log
            ORDER BY timestamp DESC
            """
        )
        rows = cur.fetchall()
        if not rows:
            return None

        best_sql: Optional[str] = None
        best_score = 0.0
        for stored_question, corrected_sql in rows:
            score = _similarity(question, stored_question or "")
            if score > best_score:
                best_score = score
                best_sql = corrected_sql

        return best_sql if best_score >= _CORRECTION_MATCH_THRESHOLD else None
    finally:
        conn.close()
