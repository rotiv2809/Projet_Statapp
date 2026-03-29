from app.agents.guardrails.schemas import GatekeeperResult
from app.pipeline import langgraph_flow


class _StubGuardrailsAgent:
    def evaluate(self, question: str) -> GatekeeperResult:
        return GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")


class _StubSQLAgent:
    def generate_sql(self, question: str, schema_text: str) -> str:
        return "SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment"


class _StubErrorAgent:
    def repair_sql(self, question: str, schema_text: str, failed_sql: str, error_message: str) -> str:
        return "SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment"


class _StubAnalysisAgent:
    def summarize(self, question, sql, columns, rows, fallback_text):
        return "Graph summary"


class _StubVizAgent:
    def generate(self, question, columns, rows, fallback_viz=None):
        return fallback_viz


class _SequenceGuardrailsAgent:
    def __init__(self, *results):
        self._results = list(results)
        self.seen_questions = []

    def evaluate(self, question: str) -> GatekeeperResult:
        self.seen_questions.append(question)
        idx = min(len(self.seen_questions) - 1, len(self._results) - 1)
        return self._results[idx]


class _RecordingSQLAgent:
    def __init__(self, *sql_values):
        self._sql_values = list(sql_values)
        self.calls = []

    def generate_sql(self, question: str, schema_text: str) -> str:
        self.calls.append({"question": question, "schema_text": schema_text})
        idx = min(len(self.calls) - 1, len(self._sql_values) - 1)
        return self._sql_values[idx]


class _RecordingErrorAgent:
    def __init__(self, *repaired_sql_values):
        self._repaired_sql_values = list(repaired_sql_values)
        self.calls = []

    def repair_sql(self, question: str, schema_text: str, failed_sql: str, error_message: str) -> str:
        self.calls.append(
            {
                "question": question,
                "schema_text": schema_text,
                "failed_sql": failed_sql,
                "error_message": error_message,
            }
        )
        idx = min(len(self.calls) - 1, len(self._repaired_sql_values) - 1)
        return self._repaired_sql_values[idx]


class _RecordingAnalysisAgent:
    def __init__(self, answer_text: str = "Graph summary"):
        self.answer_text = answer_text
        self.calls = []

    def summarize(self, question, sql, columns, rows, fallback_text):
        self.calls.append(
            {
                "question": question,
                "sql": sql,
                "columns": columns,
                "rows": rows,
                "fallback_text": fallback_text,
            }
        )
        return self.answer_text


class _RecordingVizAgent:
    def __init__(self, viz_payload=None):
        self.viz_payload = viz_payload if viz_payload is not None else {"kind": "bar"}
        self.calls = []

    def generate(self, question, columns, rows, fallback_viz=None):
        self.calls.append(
            {
                "question": question,
                "columns": columns,
                "rows": rows,
                "fallback_viz": fallback_viz,
            }
        )
        return self.viz_payload


def _install_graph_stubs(
    monkeypatch,
    *,
    guardrails_agent,
    sql_agent=None,
    error_agent=None,
    analysis_agent=None,
    viz_agent=None,
    validate_results=None,
    execute_results=None,
):
    sql_agent = sql_agent or _RecordingSQLAgent("SELECT 1")
    error_agent = error_agent or _RecordingErrorAgent("SELECT 1")
    analysis_agent = analysis_agent or _RecordingAnalysisAgent()
    viz_agent = viz_agent or _RecordingVizAgent()
    validate_results = list(validate_results or [(True, "OKAY")])
    execute_results = list(
        execute_results
        or [{"ok": True, "columns": ["segment", "count"], "rows": [["A", 3], ["B", 5]]}]
    )

    monkeypatch.setattr(langgraph_flow, "GuardrailsAgent", lambda: guardrails_agent)
    monkeypatch.setattr(langgraph_flow, "SQLAgent", lambda: sql_agent)
    monkeypatch.setattr(langgraph_flow, "ErrorAgent", lambda: error_agent)
    monkeypatch.setattr(langgraph_flow, "AnalysisAgent", lambda: analysis_agent)
    monkeypatch.setattr(langgraph_flow, "VizAgent", lambda: viz_agent)
    monkeypatch.setattr(langgraph_flow, "get_schema_text", lambda db_path: "schema")

    def _validate_sql(sql_text):
        idx = min(_validate_sql.calls, len(validate_results) - 1)
        _validate_sql.calls += 1
        return validate_results[idx]

    _validate_sql.calls = 0

    def _execute_sql(db_path, sql_text):
        idx = min(_execute_sql.calls, len(execute_results) - 1)
        _execute_sql.calls += 1
        return execute_results[idx]

    _execute_sql.calls = 0

    monkeypatch.setattr(langgraph_flow, "validate_sql", _validate_sql)
    monkeypatch.setattr(langgraph_flow, "execute_sql", _execute_sql)
    monkeypatch.setattr(langgraph_flow, "infer_plotly", lambda question, columns, rows: {"kind": "fallback"})

    return {
        "guardrails_agent": guardrails_agent,
        "sql_agent": sql_agent,
        "error_agent": error_agent,
        "analysis_agent": analysis_agent,
        "viz_agent": viz_agent,
    }


def _build_test_graph_app():
    workflow = langgraph_flow.build_text2sql_graph()
    return workflow.compile(checkpointer=langgraph_flow.MemorySaver())


def test_invoke_graph_pipeline_returns_data_payload(monkeypatch):
    monkeypatch.setattr(langgraph_flow, "_app_instance", None)
    monkeypatch.setattr(langgraph_flow, "_memory_instance", None)
    monkeypatch.setattr(langgraph_flow, "GuardrailsAgent", lambda: _StubGuardrailsAgent())
    monkeypatch.setattr(langgraph_flow, "SQLAgent", lambda: _StubSQLAgent())
    monkeypatch.setattr(langgraph_flow, "ErrorAgent", lambda: _StubErrorAgent())
    monkeypatch.setattr(langgraph_flow, "AnalysisAgent", lambda: _StubAnalysisAgent())
    monkeypatch.setattr(langgraph_flow, "VizAgent", lambda: _StubVizAgent())
    monkeypatch.setattr(langgraph_flow, "get_schema_text", lambda db_path: "schema")
    monkeypatch.setattr(langgraph_flow, "validate_sql", lambda sql: (True, "OKAY"))
    monkeypatch.setattr(
        langgraph_flow,
        "execute_sql",
        lambda db_path, sql: {
            "ok": True,
            "columns": ["segment", "count"],
            "rows": [["A", 3], ["B", 5]],
        },
    )
    monkeypatch.setattr(
        langgraph_flow,
        "format_response_dict",
        lambda columns, rows: {
            "text": "Fallback text",
            "table": "table",
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "total_rows": len(rows),
        },
    )
    monkeypatch.setattr(langgraph_flow, "infer_plotly", lambda question, columns, rows: None)

    result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        thread_id="test-thread",
    )

    assert prior == {}
    assert result["route"] == "DATA"
    assert result["sql"].startswith("SELECT segment")
    assert result["columns"] == ["segment", "count"]
    assert result["rows"] == [["A", 3], ["B", 5]]
    assert result["answer_text"].startswith("Graph summary")


def test_get_graph_app_returns_singleton(monkeypatch):
    monkeypatch.setattr(langgraph_flow, "_app_instance", None)
    monkeypatch.setattr(langgraph_flow, "_memory_instance", None)
    monkeypatch.setattr(langgraph_flow, "GuardrailsAgent", lambda: _StubGuardrailsAgent())
    monkeypatch.setattr(langgraph_flow, "SQLAgent", lambda: _StubSQLAgent())
    monkeypatch.setattr(langgraph_flow, "ErrorAgent", lambda: _StubErrorAgent())
    monkeypatch.setattr(langgraph_flow, "AnalysisAgent", lambda: _StubAnalysisAgent())
    monkeypatch.setattr(langgraph_flow, "VizAgent", lambda: _StubVizAgent())
    monkeypatch.setattr(langgraph_flow, "get_schema_text", lambda db_path: "schema")
    monkeypatch.setattr(langgraph_flow, "validate_sql", lambda sql: (True, "OKAY"))
    monkeypatch.setattr(
        langgraph_flow,
        "execute_sql",
        lambda db_path, sql: {"ok": True, "columns": ["segment", "count"], "rows": [["A", 3]]},
    )
    monkeypatch.setattr(
        langgraph_flow,
        "format_response_dict",
        lambda columns, rows: {
            "text": "Fallback text",
            "table": "table",
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "total_rows": len(rows),
        },
    )
    monkeypatch.setattr(langgraph_flow, "infer_plotly", lambda question, columns, rows: None)

    app_a = langgraph_flow.get_graph_app()
    app_b = langgraph_flow.get_graph_app()

    assert app_a is app_b


class _RecordingGraphApp:
    def __init__(self):
        self.captured_input = None
        self.captured_config = None

    def get_state(self, config):
        class _Snapshot:
            values = {
                "question": "How many clients by commune?",
                "route": "DATA",
                "missing_slots": [],
                "clarifying_questions": [],
                "columns": ["commune", "count"],
                "rows": [["full_row", 999]],
                "preview_rows": [["preview_row", 5]],
                "sql": "SELECT commune, COUNT(*) FROM clients GROUP BY commune",
            }

        return _Snapshot()

    def invoke(self, input_state, config=None):
        self.captured_input = dict(input_state)
        self.captured_config = dict(config or {})
        return {"route": "DATA", "answer_text": "ok"}


def test_invoke_graph_pipeline_prefers_preview_rows_for_memory():
    graph_app = _RecordingGraphApp()

    result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="plot a bar chart",
        thread_id="test-thread",
        graph_app=graph_app,
    )

    assert result["route"] == "DATA"
    assert prior["rows"] == [["full_row", 999]]
    assert graph_app.captured_input["prior_rows"] == [["preview_row", 5]]


def test_invoke_graph_pipeline_runs_guardrails_to_sql_transition(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
    )
    graph_app = _build_test_graph_app()

    result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        thread_id="guardrails-to-sql",
        graph_app=graph_app,
    )

    assert prior == {}
    assert result["route"] == "DATA"
    assert result["sql"] == "SELECT 1"
    assert patched["guardrails_agent"].seen_questions == ["How many clients by segment?"]
    assert patched["sql_agent"].calls[0]["question"] == "How many clients by segment?"
    assert "I can plot this data for you" in result["answer_text"]


def test_invoke_graph_pipeline_repairs_sql_after_validation_failure(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        sql_agent=_RecordingSQLAgent("BROKEN SQL"),
        error_agent=_RecordingErrorAgent("SELECT commune, COUNT(*) AS count FROM clients GROUP BY commune"),
        validate_results=[(False, "Only SELECT queries are allowed."), (True, "OKAY")],
        execute_results=[
            {"ok": True, "columns": ["commune", "count"], "rows": [["A", 3], ["B", 2]]}
        ],
    )
    graph_app = _build_test_graph_app()

    result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by commune?",
        thread_id="repair-loop",
        graph_app=graph_app,
    )

    assert result["route"] == "DATA"
    assert result["sql"].startswith("SELECT commune")
    assert [attempt["stage"] for attempt in result["attempts"]] == ["validation", "repair", "execution"]
    assert patched["error_agent"].calls[0]["failed_sql"] == "BROKEN SQL"


def test_invoke_graph_pipeline_routes_viz_followup_without_requerying_sql(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        sql_agent=_RecordingSQLAgent("SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment"),
        viz_agent=_RecordingVizAgent({"kind": "bar", "title": "By segment"}),
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        thread_id="viz-followup",
        graph_app=graph_app,
    )
    second_result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="plot a bar chart",
        thread_id="viz-followup",
        graph_app=graph_app,
    )

    assert first_result["route"] == "DATA"
    assert prior["route"] == "DATA"
    assert second_result["route"] == "VIZ_FOLLOWUP"
    assert second_result["viz"] == {"kind": "bar", "title": "By segment"}
    assert len(patched["sql_agent"].calls) == 1
    assert len(patched["guardrails_agent"].seen_questions) == 1
    assert "plot a bar chart" in patched["viz_agent"].calls[0]["question"]
    assert "How many clients by segment?" in patched["viz_agent"].calls[0]["question"]


def test_invoke_graph_pipeline_returns_chat_for_greeting(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="OUT OF SCOPE", parsed_intent="greeting", notes="Hello!")
        ),
    )
    graph_app = _build_test_graph_app()

    result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="hello",
        thread_id="greeting",
        graph_app=graph_app,
    )

    assert result["route"] == "CHAT"
    assert result["answer_text"] == "Hello!"
    assert patched["sql_agent"].calls == []


def test_invoke_graph_pipeline_merges_clarification_into_followup_question(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(
                status="NEEDS CLARIFICATION",
                parsed_intent="ranking",
                missing_slots=["metric", "time_range"],
                clarifying_questions=["Which metric?", "Which period?"],
                notes="ranking_missing_metric_time_range",
            ),
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
        ),
        sql_agent=_RecordingSQLAgent("SELECT commune, COUNT(*) AS count FROM clients GROUP BY commune"),
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="Top 10 communes",
        thread_id="clarification-memory",
        graph_app=graph_app,
    )
    second_result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="number of clients in 2024",
        thread_id="clarification-memory",
        graph_app=graph_app,
    )

    merged_question = patched["guardrails_agent"].seen_questions[1]

    assert first_result["route"] == "CLARIFY"
    assert prior["route"] == "CLARIFY"
    assert second_result["route"] == "DATA"
    assert "Top 10 communes" in merged_question
    assert "User clarification" in merged_question
    assert "number of clients in 2024" in merged_question
