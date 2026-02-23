from __future__ import annotations 
from typing import Dict, Any
from app.db.sqlite import run_query
from app.safety.sql_validator import validate_sql


def execute_sql(sqlite_path:str,sql:str, max_rows :int = 200)-> Dict[str, Any]:
    ok, reason = validate_sql(sql)
    if not ok: 
        return {"ok":False, "error": reason, "sql":sql}
    
    try: 
        cols, rows = run_query(sqlite_path, sql, max_rows=max_rows)
        return {"ok": True, "sql": sql, "columns":cols, "rows":rows}

    except Exception as e:
        return {"ok": False, "error": f"SQL execution error: {e}", "sql":sql}