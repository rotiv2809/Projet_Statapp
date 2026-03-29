from app.pipeline import expert_review


def test_run_reviewed_sql_executes_and_logs_correction(monkeypatch):
    logged = {}

    monkeypatch.setattr(
        expert_review,
        "execute_sql",
        lambda db_path, sql: {
            "ok": True,
            "columns": ["segment", "count"],
            "rows": [["A", 3], ["B", 5]],
        },
    )
    monkeypatch.setattr(
        expert_review,
        "format_response_dict",
        lambda columns, rows: {
            "text": "Results: 2 rows. Preview: 2 rows.",
            "table": "table",
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "total_rows": len(rows),
        },
    )
    monkeypatch.setattr(
        expert_review,
        "infer_plotly",
        lambda question, columns, rows: {"type": "plotly", "figure": {"data": []}},
    )
    monkeypatch.setattr(
        expert_review,
        "log_correction",
        lambda **kwargs: logged.update(kwargs),
    )

    result = expert_review.run_reviewed_sql(
        db_path="data/statapp.sqlite",
        question="How many clients by segment?",
        generated_sql="SELECT segment FROM clients",
        reviewed_sql="SELECT segment, COUNT(*) AS count FROM clients GROUP BY segment",
        review_user="admin",
    )

    assert result["ok"] is True
    assert result["correction_applied"] is True
    assert result["saved_correction"] is True
    assert result["review_user"] == "admin"
    assert "Executed expert-corrected SQL and saved the correction." in result["answer_text"]
    assert logged["question"] == "How many clients by segment?"
    assert logged["user"] == "admin"


def test_run_reviewed_sql_skips_correction_log_when_sql_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        expert_review,
        "execute_sql",
        lambda db_path, sql: {"ok": True, "columns": ["n"], "rows": [[1]]},
    )
    monkeypatch.setattr(
        expert_review,
        "format_response_dict",
        lambda columns, rows: {
            "text": "Results: 1 rows. Preview: 1 rows.",
            "table": "table",
            "preview_rows": rows,
            "preview_row_count": len(rows),
            "total_rows": len(rows),
        },
    )
    monkeypatch.setattr(expert_review, "infer_plotly", lambda question, columns, rows: None)

    called = {"log": False}

    def _log_correction(**kwargs):
        called["log"] = True

    monkeypatch.setattr(expert_review, "log_correction", _log_correction)

    result = expert_review.run_reviewed_sql(
        db_path="data/statapp.sqlite",
        question="How many clients?",
        generated_sql="SELECT COUNT(*) AS n FROM clients",
        reviewed_sql="SELECT COUNT(*) AS n FROM clients",
        review_user="expert",
    )

    assert result["ok"] is True
    assert result["correction_applied"] is False
    assert result["saved_correction"] is False
    assert called["log"] is False
    assert "Executed reviewed SQL." in result["answer_text"]


def test_run_reviewed_sql_returns_error_for_invalid_reviewed_sql(monkeypatch):
    monkeypatch.setattr(
        expert_review,
        "execute_sql",
        lambda db_path, sql: {"ok": False, "error": "Only SELECT queries are allowed.", "sql": sql},
    )

    result = expert_review.run_reviewed_sql(
        db_path="data/statapp.sqlite",
        question="How many clients?",
        generated_sql="SELECT COUNT(*) AS n FROM clients",
        reviewed_sql="DELETE FROM clients",
        review_user="expert",
    )

    assert result["ok"] is False
    assert result["stage"] == "expert_review"
    assert "Expert SQL review failed" in result["message"]
