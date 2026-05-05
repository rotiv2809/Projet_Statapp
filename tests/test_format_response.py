from app.formatters.format_response import format_response, with_plot_suggestion


def test_format_response_two_columns_reports_actual_preview_count():
    rows = [[f"commune_{i}", i] for i in range(30)]

    result = format_response(["commune", "count"], rows, max_preview_rows=20)

    assert result.preview_row_count == 20
    assert len(result.preview_rows) == 20
    assert result.total_rows == 30
    assert "The top communes are" in result.text
    assert "first 20 rows out of 30" in result.text


def test_format_response_single_number_is_natural():
    result = format_response(["nombre_clients"], [[5000]])

    assert result.text == "There are 5,000 clients."


def test_format_response_comparison_style_for_two_time_points():
    result = format_response(["year", "count"], [["2023", 120], ["2024", 150]])

    assert "2024 is higher than 2023 by 30" in result.text


def test_format_response_trend_style_for_time_series():
    result = format_response(["month", "count"], [["January", 10], ["March", 25], ["April", 15]])

    assert "The peak was in March" in result.text


def test_with_plot_suggestion_is_idempotent():
    base = "Summary"

    once = with_plot_suggestion(base)
    twice = with_plot_suggestion(once)

    assert once == twice
    assert "I can plot this data for you" in once
