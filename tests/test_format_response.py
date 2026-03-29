from app.formatters.format_response import format_response, with_plot_suggestion


def test_format_response_two_columns_reports_actual_preview_count():
    rows = [[f"commune_{i}", i] for i in range(30)]

    result = format_response(["commune", "count"], rows, max_preview_rows=20)

    assert result.preview_row_count == 20
    assert len(result.preview_rows) == 20
    assert result.total_rows == 30
    assert "(showing 20/30)" in result.text


def test_with_plot_suggestion_is_idempotent():
    base = "Summary"

    once = with_plot_suggestion(base)
    twice = with_plot_suggestion(once)

    assert once == twice
    assert "I can plot this data for you" in once
