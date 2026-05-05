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
    monkeypatch.setattr(langgraph_flow, "get_prompt_schema_text", lambda db_path, question: "schema")

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
    monkeypatch.setattr(langgraph_flow, "fetch_similar_correction", lambda db_path, question: None)

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
    monkeypatch.setattr(langgraph_flow, "get_prompt_schema_text", lambda db_path, question: "schema")
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
    assert result["answer_text"].startswith("Fallback text")


def test_get_graph_app_returns_singleton(monkeypatch):
    monkeypatch.setattr(langgraph_flow, "_app_instance", None)
    monkeypatch.setattr(langgraph_flow, "_memory_instance", None)
    monkeypatch.setattr(langgraph_flow, "GuardrailsAgent", lambda: _StubGuardrailsAgent())
    monkeypatch.setattr(langgraph_flow, "SQLAgent", lambda: _StubSQLAgent())
    monkeypatch.setattr(langgraph_flow, "ErrorAgent", lambda: _StubErrorAgent())
    monkeypatch.setattr(langgraph_flow, "AnalysisAgent", lambda: _StubAnalysisAgent())
    monkeypatch.setattr(langgraph_flow, "VizAgent", lambda: _StubVizAgent())
    monkeypatch.setattr(langgraph_flow, "get_prompt_schema_text", lambda db_path, question: "schema")
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
                "metric": "clients",
                "dimensions": ["commune"],
                "time_range": {"kind": "year", "value": "2024"},
                "filters": {"scope": "Cambodia"},
                "sort_by": "clients",
                "sort_direction": "desc",
                "aggregation_intent": "count",
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
    assert graph_app.captured_input["prior_metric"] == "clients"
    assert graph_app.captured_input["prior_dimensions"] == ["commune"]
    assert graph_app.captured_input["prior_filters"] == {"scope": "Cambodia"}


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
    assert result["result_object"]["chart_ready"] is True
    assert result["result_object"]["suggested_chart"] == "bar chart"
    assert "How many clients by segment?" in patched["guardrails_agent"].seen_questions[0]
    assert "How many clients by segment?" in patched["sql_agent"].calls[0]["question"]
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
    assert first_result["result_object"]["semantic_type"] == "categorical_comparison"
    assert prior["route"] == "DATA"
    assert second_result["route"] == "VIZ_FOLLOWUP"
    assert second_result["viz"] == {"kind": "bar", "title": "By segment"}
    assert "bar chart" in second_result["answer_text"]
    assert len(patched["sql_agent"].calls) == 1
    assert len(patched["guardrails_agent"].seen_questions) == 1
    assert "plot a bar chart" in patched["viz_agent"].calls[0]["question"]
    assert "How many clients by segment?" in patched["viz_agent"].calls[0]["question"]


def test_invoke_graph_pipeline_returns_viz_no_data_when_visualization_cannot_be_built(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        sql_agent=_RecordingSQLAgent("SELECT COUNT(*) AS nombre_clients FROM clients"),
        viz_agent=_RecordingVizAgent(None),
        execute_results=[
            {"ok": True, "columns": ["nombre_clients"], "rows": [[5000]]}
        ],
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients are there in the database?",
        thread_id="viz-not-supported",
        graph_app=graph_app,
    )
    second_result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="yes plot using pie chart",
        thread_id="viz-not-supported",
        graph_app=graph_app,
    )

    assert first_result["route"] == "DATA"
    assert prior["route"] == "DATA"
    assert second_result["route"] == "VIZ_UNSUPPORTED"
    assert second_result["viz"] is None
    assert "pie chart does not fit a single total" in second_result["answer_text"]
    assert len(patched["sql_agent"].calls) == 1


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

    merged_question = patched["guardrails_agent"].seen_questions[0]

    assert first_result["route"] == "CLARIFY"
    assert "rank the communes" in first_result["answer_text"].lower()
    assert prior["route"] == "CLARIFY"
    assert second_result["route"] == "DATA"
    assert "Top 10 communes" in merged_question
    assert "User clarification" in merged_question
    assert "number of clients in 2024" in merged_question


def test_invoke_graph_pipeline_returns_viz_no_data_after_clarification_when_user_only_requests_chart(monkeypatch):
    _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
        ),
        sql_agent=_RecordingSQLAgent("SELECT commune, COUNT(*) AS count FROM clients GROUP BY commune"),
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="Top 10 communes",
        thread_id="clarification-then-chart",
        graph_app=graph_app,
    )
    second_result, prior = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="plot a bar chart",
        thread_id="clarification-then-chart",
        graph_app=graph_app,
    )

    assert first_result["route"] == "CLARIFY"
    assert prior["route"] == "CLARIFY"
    assert second_result["route"] == "VIZ_NO_DATA"
    assert "can't plot yet" in second_result["answer_text"]
    assert "Top 10 communes" in second_result["answer_text"]


def test_invoke_graph_pipeline_uses_specific_refusal_message_for_unsafe_sql(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="OUT OF SCOPE", parsed_intent="unsafe_sql_or_injection", notes="Refused"),
        ),
    )
    graph_app = _build_test_graph_app()

    result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="DROP TABLE clients",
        thread_id="unsafe-refusal",
        graph_app=graph_app,
    )

    assert result["route"] == "OUT_OF_SCOPE"
    assert "destructive or raw SQL" in result["answer_text"]
    assert patched["sql_agent"].calls == []


def test_invoke_graph_pipeline_merges_contextual_followup_into_previous_data_question(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
        ),
        sql_agent=_RecordingSQLAgent(
            "SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment",
            "SELECT segment, COUNT(*) AS count FROM clients WHERE year = 2024 GROUP BY segment",
        ),
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        thread_id="contextual-followup",
        graph_app=graph_app,
    )
    second_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="only for 2024",
        thread_id="contextual-followup",
        graph_app=graph_app,
    )

    merged_question = patched["guardrails_agent"].seen_questions[1]

    assert first_result["route"] == "DATA"
    assert second_result["route"] == "DATA"
    assert "intent: filter_change" in merged_question
    assert "original question: only for 2024" in merged_question
    assert "metric: clients" in merged_question


def test_invoke_graph_pipeline_merges_elliptical_filter_followup(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
        ),
        sql_agent=_RecordingSQLAgent(
            "SELECT commune, COUNT(*) AS count FROM clients GROUP BY commune",
            "SELECT commune, COUNT(*) AS count FROM clients WHERE pays = 'Cambodia' GROUP BY commune",
        ),
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by commune in 2024?",
        thread_id="elliptical-followup",
        graph_app=graph_app,
    )
    second_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="and for Cambodia?",
        thread_id="elliptical-followup",
        graph_app=graph_app,
    )

    merged_question = patched["guardrails_agent"].seen_questions[1]

    assert first_result["route"] == "DATA"
    assert second_result["route"] == "DATA"
    assert "intent: filter_change" in merged_question
    assert "original question: and for Cambodia?" in merged_question
    assert "country" in merged_question


def test_invoke_graph_pipeline_reuses_logged_correction_before_llm(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        sql_agent=_RecordingSQLAgent("SELECT should_not_be_used"),
    )
    monkeypatch.setattr(
        langgraph_flow,
        "fetch_similar_correction",
        lambda db_path, question: "SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment",
    )
    graph_app = _build_test_graph_app()

    result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        thread_id="reuse-correction",
        graph_app=graph_app,
    )

    assert result["route"] == "DATA"
    assert result["reused_correction"] is True
    assert result["sql_source"] == "expert_memory"
    assert result["sql"].startswith("SELECT segment")
    assert patched["sql_agent"].calls == []


def test_invoke_graph_pipeline_answers_explanation_followup_without_sql(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        analysis_agent=_RecordingAnalysisAgent("There are 5,000 clients in the database."),
        sql_agent=_RecordingSQLAgent("SELECT COUNT(*) AS nombre_clients FROM clients"),
        execute_results=[{"ok": True, "columns": ["nombre_clients"], "rows": [[5000]]}],
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients are there?",
        thread_id="explain-followup",
        graph_app=graph_app,
    )
    second_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="explain that",
        thread_id="explain-followup",
        graph_app=graph_app,
    )

    assert first_result["route"] == "DATA"
    assert second_result["route"] == "CHAT"
    assert "Here is what I mean" in second_result["answer_text"]
    assert len(patched["sql_agent"].calls) == 1


def test_invoke_graph_pipeline_explains_empty_result_without_rerunning_sql(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed")
        ),
        analysis_agent=_RecordingAnalysisAgent("No results."),
        sql_agent=_RecordingSQLAgent("SELECT commune, COUNT(*) AS count FROM clients WHERE pays = 'Cambodia'"),
        execute_results=[{"ok": True, "columns": ["commune", "count"], "rows": []}],
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients by commune in Cambodia?",
        thread_id="empty-explanation",
        graph_app=graph_app,
    )
    second_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="why is that empty?",
        thread_id="empty-explanation",
        graph_app=graph_app,
    )

    assert first_result["route"] == "DATA"
    assert second_result["route"] == "CHAT"
    assert "returned no rows" in second_result["answer_text"]
    assert len(patched["sql_agent"].calls) == 1


def test_invoke_graph_pipeline_resets_context(monkeypatch):
    patched = _install_graph_stubs(
        monkeypatch,
        guardrails_agent=_SequenceGuardrailsAgent(
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
            GatekeeperResult(status="READY_FOR_SQL", parsed_intent="sql_query", notes="Allowed"),
        ),
        sql_agent=_RecordingSQLAgent("SELECT COUNT(*) AS nombre_clients FROM clients", "SELECT 1"),
        execute_results=[
            {"ok": True, "columns": ["nombre_clients"], "rows": [[5000]]},
            {"ok": True, "columns": ["value"], "rows": [[1]]},
        ],
    )
    graph_app = _build_test_graph_app()

    first_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many clients are there?",
        thread_id="reset-context",
        graph_app=graph_app,
    )
    reset_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="start over",
        thread_id="reset-context",
        graph_app=graph_app,
    )
    third_result, _ = langgraph_flow.invoke_graph_pipeline(
        db_path="data/statapp.sqlite",
        question="How many transactions are there?",
        thread_id="reset-context",
        graph_app=graph_app,
    )

    assert first_result["route"] == "DATA"
    assert reset_result["route"] == "CHAT"
    assert "cleared the current analysis context" in reset_result["answer_text"]
    assert third_result["route"] == "DATA"
    assert len(patched["sql_agent"].calls) == 2
