from app.agents.guardrails.schemas import GatekeeperResult
from app.pipeline import data_pipeline


class _StubGuardrailsAgent:
    def __init__(self, result):
        self._result = result

    def evaluate(self, question: str) -> GatekeeperResult:
        return self._result


class _StubSQLAgent:
    def __init__(self, sql: str):
        self._sql = sql

    def generate_sql(self, question: str, schema_text: str) -> str:
        return self._sql


class _StubErrorAgent:
    def __init__(self, repaired_sql: str):
        self._repaired_sql = repaired_sql

    def repair_sql(self, question: str, schema_text: str, failed_sql: str, error_message: str) -> str:
        return self._repaired_sql


class _StubAnalysisAgent:
    def __init__(self, answer_text: str):
        self._answer_text = answer_text

    def summarize(self, question, sql, columns, rows, fallback_text):
        return self._answer_text


class _FailingSQLAgent:
    def generate_sql(self, question: str, schema_text: str) -> str:
        raise AssertionError("SQLAgent.generate_sql should not be called when memory is reused")


def _patch_pipeline(
    monkeypatch,
    *,
    gatekeeper_result: GatekeeperResult,
    sql: str = "SELECT 1",
    repaired_sql: str = "SELECT 1",
    validate_results=None,
    execute_result=None,
    answer_text: str = "Summary",
):
    validate_results = list(validate_results or [(True, "OKAY")])
    execute_result = execute_result or {
        "ok": True,
        "columns": ["segment", "count"],
        "rows": [["A", 3]],
    }

    monkeypatch.setattr(data_pipeline, "get_prompt_schema_text", lambda db_path, question: "schema")
    monkeypatch.setattr(data_pipeline, "GuardrailsAgent", lambda: _StubGuardrailsAgent(gatekeeper_result))
    monkeypatch.setattr(data_pipeline, "SQLAgent", lambda: _StubSQLAgent(sql))
    monkeypatch.setattr(data_pipeline, "ErrorAgent", lambda: _StubErrorAgent(repaired_sql))
    monkeypatch.setattr(data_pipeline, "AnalysisAgent", lambda: _StubAnalysisAgent(answer_text))
    monkeypatch.setattr(
        data_pipeline,
        "format_response_dict",
        lambda columns, rows: {
            "text": "Fallback text",
            "table": "table",
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "total_rows": len(rows),
        },
    )

    def _validate_sql(sql_text):
        return validate_results.pop(0)

    monkeypatch.setattr(data_pipeline, "validate_sql", _validate_sql)
    monkeypatch.setattr(data_pipeline, "execute_sql", lambda db_path, sql_text: execute_result)
    monkeypatch.setattr(data_pipeline, "fetch_similar_correction", lambda db_path, question: None)


def test_run_data_pipeline_returns_chat_for_greeting(monkeypatch):
    greeting = GatekeeperResult(
        status="OUT OF SCOPE",
        parsed_intent="greeting",
        notes="Hello!",
    )
    _patch_pipeline(monkeypatch, gatekeeper_result=greeting)

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "hello")

    assert result["ok"] is True
    assert result["route"] == "CHAT"
    assert result["message"] == "Hello!"


def test_run_data_pipeline_returns_clarification_payload(monkeypatch):
    clarification = GatekeeperResult(
        status="NEEDS CLARIFICATION",
        missing_slots=["metric", "time_range"],
        clarifying_questions=["Which metric?", "Which period?"],
        notes="ranking_missing_metric_time_range",
    )
    _patch_pipeline(monkeypatch, gatekeeper_result=clarification)

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "Top 10 communes")

    assert result["ok"] is False
    assert result["route"] == "CLARIFY"
    assert result["message"] == "Which metric?"
    assert result["clarifying_questions"] == ["Which metric?", "Which period?"]


def test_run_data_pipeline_returns_successful_data_payload(monkeypatch):
    ready = GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
    _patch_pipeline(
        monkeypatch,
        gatekeeper_result=ready,
        sql="SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment",
        execute_result={"ok": True, "columns": ["segment", "count"], "rows": [["A", 3], ["B", 5]]},
        answer_text="Here is the segment summary.",
    )

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "How many clients by segment?")

    assert result["ok"] is True
    assert result["route"] == "DATA"
    assert result["sql"].startswith("SELECT segment")
    assert result["answer_text"].startswith("Here is the segment summary.")
    assert result["result_object"]["chart_ready"] is True
    assert "I can plot this data for you" in result["answer_text"]
    assert result["attempts"][0]["stage"] == "execution"


def test_run_data_pipeline_does_not_suggest_plot_for_single_value_result(monkeypatch):
    ready = GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
    _patch_pipeline(
        monkeypatch,
        gatekeeper_result=ready,
        sql="SELECT COUNT(*) AS nombre_clients FROM clients",
        execute_result={"ok": True, "columns": ["nombre_clients"], "rows": [[5000]]},
        answer_text="There are 5,000 distinct clients in the database.",
    )

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "How many clients are there?")

    assert result["ok"] is True
    assert "I can plot this data for you" not in result["answer_text"]


def test_run_data_pipeline_repairs_after_validation_failure(monkeypatch):
    ready = GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
    _patch_pipeline(
        monkeypatch,
        gatekeeper_result=ready,
        sql="BROKEN SQL",
        repaired_sql="SELECT commune, COUNT(*) AS count FROM clients GROUP BY commune",
        validate_results=[(False, "Only SELECT queries are allowed."), (True, "OKAY")],
    )

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "How many clients by commune?")

    assert result["ok"] is True
    assert result["sql"].startswith("SELECT commune")
    assert result["retry_count"] == 1
    assert result["attempts"][0]["stage"] == "validation"
    assert result["attempts"][1]["stage"] == "execution"


def test_run_data_pipeline_reuses_logged_correction_before_llm(monkeypatch):
    ready = GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
    _patch_pipeline(
        monkeypatch,
        gatekeeper_result=ready,
        answer_text="Correction memory answer.",
    )
    monkeypatch.setattr(
        data_pipeline,
        "fetch_similar_correction",
        lambda db_path, question: "SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment",
    )
    monkeypatch.setattr(data_pipeline, "SQLAgent", lambda: _FailingSQLAgent())

    result = data_pipeline.run_data_pipeline("data/statapp.sqlite", "How many clients by segment?")

    assert result["ok"] is True
    assert result["reused_correction"] is True
    assert result["sql_source"] == "expert_memory"
    assert result["sql"].startswith("SELECT segment")
