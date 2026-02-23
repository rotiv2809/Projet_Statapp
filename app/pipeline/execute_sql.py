from __future__ import annotations
import os
from typing import Dict, Any
from app.safety.sql_validator import validate_sql


def execute_sql(sql: str, max_rows: int = 200, sqlite_path: str = None) -> Dict[str, Any]:
    """
    Execute SQL against the configured backend (Supabase or SQLite).

    Backend is chosen by the DB_BACKEND env var:
      - "supabase" → uses SUPABASE_DB_URL (direct Postgres connection)
      - "sqlite"   → uses sqlite_path argument or SQLITE_PATH env var

    Auto-detection: if SUPABASE_URL is set and DB_BACKEND is not explicitly
    "sqlite", Supabase is used.
    """
    ok, reason = validate_sql(sql)
    if not ok:
        return {"ok": False, "error": reason, "sql": sql}

    backend = _resolve_backend()

    try:
        if backend == "supabase":
            from app.db.supabase import run_query
            cols, rows = run_query(sql, max_rows=max_rows)
        else:
            from app.db.sqlite import run_query
            path = sqlite_path or os.getenv("SQLITE_PATH", "data/statapp.sqlite")
            cols, rows = run_query(path, sql, max_rows=max_rows)

        return {"ok": True, "sql": sql, "columns": cols, "rows": rows}

    except Exception as e:
        return {"ok": False, "error": f"SQL execution error: {e}", "sql": sql}


def _resolve_backend() -> str:
    explicit = os.getenv("DB_BACKEND", "").lower()
    if explicit in ("supabase", "sqlite"):
        return explicit
    if os.getenv("SUPABASE_URL"):
        return "supabase"
    return "sqlite"