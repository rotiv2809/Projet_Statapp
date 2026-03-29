import sqlite3
from typing import Optional

def _normalize_question(question: str) -> str:
    return " ".join((question or "").strip().lower().split())


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
    cur = conn.cursor()
    _ensure_corrections_table(cur)
    cur.execute(
        """
        INSERT INTO corrections_log (question, normalized_question, generated_sql, corrected_sql, user)
        VALUES (?, ?, ?, ?, ?)
        """,
        (question, _normalize_question(question), generated_sql, corrected_sql, user)
    )
    conn.commit()
    conn.close()

def fetch_similar_correction(db_path: str, question: str) -> Optional[str]:
    """Fetch a corrected SQL for a similar question, if available."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    _ensure_corrections_table(cur)
    normalized_question = _normalize_question(question)
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
    if not row:
        cur.execute(
            """
            SELECT corrected_sql
            FROM corrections_log
            WHERE question LIKE ? OR normalized_question LIKE ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (f"%{question}%", f"%{normalized_question}%"),
        )
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None
