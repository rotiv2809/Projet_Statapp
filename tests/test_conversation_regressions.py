import json
from pathlib import Path

import pytest

from app.agents.guardrails.router import route_message
from app.agents.guardrails.schemas import GatekeeperResult
from app.formatters.format_response import format_response
from app.formatters.viz_plotly import build_visualization_guidance
from app.pipeline import langgraph_flow


DATASET_PATH = Path(__file__).parent / "fixtures" / "conversation_regressions.json"


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
    def __init__(self, repaired_sql: str):
        self.repaired_sql = repaired_sql

    def repair_sql(self, question: str, schema_text: str, failed_sql: str, error_message: str) -> str:
        return self.repaired_sql


class _RecordingAnalysisAgent:
    def summarize(self, question, sql, columns, rows, fallback_text):
        return fallback_text


class _RecordingVizAgent:
    def __init__(self, viz_payload=None):
        self.viz_payload = viz_payload

    def generate(self, question, columns, rows, fallback_viz=None):
        return self.viz_payload if self.viz_payload is not None else fallback_viz


def _load_dataset():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _case_ids(cases):
    return [case["name"] for case in cases]


def _make_gatekeeper(payload):
    return GatekeeperResult(
        status=payload["status"],
        parsed_intent=payload.get("parsed_intent"),
        metric=payload.get("metric"),
        dimensions=payload.get("dimensions", []),
        time_range=payload.get("time_range"),
        filters=payload.get("filters", {}),
        missing_slots=payload.get("missing_slots", []),
        clarifying_questions=payload.get("clarifying_questions", []),
        notes=payload.get("notes"),
    )


def _install_graph_regression_stubs(
    monkeypatch,
    *,
    guardrails_agent,
    sql_agent,
    error_agent=None,
    execute_results=None,
):
    error_agent = error_agent or _RecordingErrorAgent("SELECT 1")
    execute_results = list(
        execute_results
        or [{"ok": True, "columns": ["segment", "count"], "rows": [["A", 3], ["B", 5]]}]
    )

    monkeypatch.setattr(langgraph_flow, "GuardrailsAgent", lambda: guardrails_agent)
    monkeypatch.setattr(langgraph_flow, "SQLAgent", lambda: sql_agent)
    monkeypatch.setattr(langgraph_flow, "ErrorAgent", lambda: error_agent)
    monkeypatch.setattr(langgraph_flow, "AnalysisAgent", lambda: _RecordingAnalysisAgent())
    monkeypatch.setattr(langgraph_flow, "VizAgent", lambda: _RecordingVizAgent())
    monkeypatch.setattr(langgraph_flow, "get_prompt_schema_text", lambda db_path, question: "schema")

    def _validate_sql(sql_text):
        if sql_text == "BROKEN SQL":
            return (False, "Only SELECT queries are allowed.")
        return (True, "OKAY")

    def _execute_sql(db_path, sql_text):
        idx = min(_execute_sql.calls, len(execute_results) - 1)
        _execute_sql.calls += 1
        return execute_results[idx]

    _execute_sql.calls = 0

    monkeypatch.setattr(langgraph_flow, "validate_sql", _validate_sql)
    monkeypatch.setattr(langgraph_flow, "execute_sql", _execute_sql)
    monkeypatch.setattr(langgraph_flow, "fetch_similar_correction", lambda db_path, question: None)

    return langgraph_flow.build_text2sql_graph().compile(checkpointer=langgraph_flow.MemorySaver())


def _run_graph_case(monkeypatch, case):
    turns = case["turns"]
    guardrails_agent = _SequenceGuardrailsAgent(*[_make_gatekeeper(turn["guardrails"]) for turn in turns])
    sql_agent = _RecordingSQLAgent(*[turn["sql"] for turn in turns])
    execute_results = [turn["execute_result"] for turn in turns]
    error_agent = _RecordingErrorAgent(case.get("repair_sql", "SELECT 1"))
    graph_app = _install_graph_regression_stubs(
        monkeypatch,
        guardrails_agent=guardrails_agent,
        sql_agent=sql_agent,
        error_agent=error_agent,
        execute_results=execute_results,
    )

    results = []
    for idx, turn in enumerate(turns):
        result, _ = langgraph_flow.invoke_graph_pipeline(
            db_path="data/statapp.sqlite",
            question=turn["user"],
            thread_id="regression-{}".format(case["name"]),
            graph_app=graph_app,
        )
        results.append(result)

    return results, guardrails_agent


@pytest.mark.parametrize("case", _load_dataset(), ids=_case_ids(_load_dataset()))
def test_conversation_regression_dataset(case, monkeypatch):
    kind = case["kind"]

    if kind == "router":
        decision = route_message(case["input"]["prompt"])
        assert decision.route == case["expect"]["route"]
        return

    if kind == "formatter":
        result = format_response(case["input"]["columns"], case["input"]["rows"])
        assert result.text == case["expect"]["text"]
        return

    if kind == "viz_guidance":
        text = build_visualization_guidance(
            case["input"]["question"],
            case["input"]["columns"],
            case["input"]["rows"],
        )
        assert case["expect"]["text_contains"] in text
        return

    if kind == "graph":
        results, guardrails_agent = _run_graph_case(monkeypatch, case)
        final_result = results[-1]
        expect = case["expect"]

        if "route" in expect:
            assert final_result["route"] == expect["route"]
        if "answer_text_contains" in expect:
            answer_text = final_result.get("answer_text", "")
            for fragment in expect["answer_text_contains"]:
                assert fragment in answer_text
        if "attempt_stages" in expect:
            assert [attempt["stage"] for attempt in final_result["attempts"]] == expect["attempt_stages"]
        if "seen_question_contains" in expect:
            merged_question = guardrails_agent.seen_questions[-1]
            for fragment in expect["seen_question_contains"]:
                assert fragment in merged_question
        return

    raise AssertionError("Unknown regression case kind: {}".format(kind))
