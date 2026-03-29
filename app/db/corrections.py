import sqlite3
from typing import Optional

def log_correction(db_path: str, question: str, generated_sql: str, corrected_sql: str, user: str = "expert") -> None:
    """Log an expert correction to the corrections_log table."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS corrections_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            generated_sql TEXT NOT NULL,
            corrected_sql TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            user TEXT
        )
        """
    )
    cur.execute(
        "INSERT INTO corrections_log (question, generated_sql, corrected_sql, user) VALUES (?, ?, ?, ?)",
        (question, generated_sql, corrected_sql, user)
    )
    conn.commit()
    conn.close()

def fetch_similar_correction(db_path: str, question: str) -> Optional[str]:
    """Fetch a corrected SQL for a similar question, if available."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT corrected_sql FROM corrections_log WHERE question LIKE ? ORDER BY timestamp DESC LIMIT 1",
        (f"%{question}%",)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
