from typing import Any, Dict
from app.db.sqlite import get_schema_text

from app.agents.sql_agent import SQLAgent
from app.safety.sql_validator import validate_sql
from app.pipeline.execute_sql import execute_sql
from app.formatters.viz_plotly import infer_plotly

from gatekeeper.gatekeeper import gatekeep

from app.formatters.format_response import format_response_dict
def run_data_pipeline(db_path: str, question: str) -> Dict[str,Any]:

    schema_text = get_schema_text(db_path)
    gk = gatekeep(question)
    if gk.status == "OUT OF SCOPE":
        return {
            "ok": False,
            "stage": "gatekeeper",
            "status": gk.status,
            "reason": gk.parsed_intent,
            "message": "Request refused by safety policy.",
            "notes": gk.notes
        }
    if gk.status == "NEED CLARIFICATION":
        return {
            "ok":False,
            "stage":"gatekeeper",
            "status":gk.status,
            "message":"Need clarification before query the database.",
            "clarifying_questions": gk.clarifying_question,
            "missing_slots": gk.missing_slots,
            "notes": gk.notes
        }
    
    # SQL generation
    agent = SQLAgent()
    sql = agent.generate_sql(question, schema_text=schema_text)
    
    # SQL validation 
    is_ok, reason = validate_sql(sql)
    if not is_ok:
        return {
            "ok": False,
            "stage": "sql_validator",
            "status": "BLOCKED",
            "sql":sql,
            "reason": reason, 
            "message": "Generated SQL blocjed by validator"
        }    
    # SQL execution
    exec_res = execute_sql(db_path,sql)
    if not exec_res.get("ok"):
        return {
            "ok":False,
            "stage":"execution",
            "sql": sql,
            "error": exec_res.get("error")
        }
    formatted = format_response_dict(exec_res.get("columns", []), exec_res.get("rows", []))
    viz = infer_plotly(question, exec_res["columns"], exec_res["rows"])
    return {
        "ok": True,
        "stage": "done",
        "sql": sql,
        "columns": exec_res.get("columns", []),
        "rows": exec_res.get("rows", []),
        "row_count": len(exec_res.get("rows", [])),
        "answer_text": formatted["text"],
        "answer_table": formatted["table"],
        "preview_rows": formatted["preview_rows"],
        "preview_row_count": formatted["preview_row_count"],
        "total_rows": formatted["total_rows"],
        "viz": viz
    }