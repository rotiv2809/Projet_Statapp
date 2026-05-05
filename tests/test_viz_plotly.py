from app.formatters.viz_plotly import (
    build_visualization_guidance,
    can_visualize,
    describe_result_set,
    infer_plotly,
    requested_chart_type,
    supports_visualization_request,
)


def test_can_visualize_rejects_single_value_result():
    assert can_visualize(["nombre_clients"], [[5000]]) is False


def test_requested_chart_type_uses_user_request():
    assert requested_chart_type("please show me a pie chart") == "pie chart"


def test_describe_result_set_marks_grouped_result_chart_ready():
    profile = describe_result_set(["commune", "nombre_clients"], [["A", 10], ["B", 8]])

    assert profile["semantic_type"] == "categorical_comparison"
    assert profile["chart_ready"] is True
    assert profile["suggested_chart"] == "bar chart"


def test_supports_visualization_request_accepts_time_series_line_chart():
    assert supports_visualization_request(
        "show this as a line chart",
        ["month", "count"],
        [["2024-01", 10], ["2024-02", 15]],
    ) is True


def test_supports_visualization_request_rejects_pie_for_too_many_categories():
    rows = [[f"segment_{i}", i + 1] for i in range(9)]
    assert supports_visualization_request("use a pie chart", ["segment", "count"], rows) is False


def test_build_visualization_guidance_explains_why_pie_chart_is_invalid_for_single_total():
    text = build_visualization_guidance("show me a pie chart", ["nombre_clients"], [[5000]])

    assert "pie chart" in text
    assert "clients by segment" in text


def test_build_visualization_guidance_suggests_line_chart_for_time_series():
    text = build_visualization_guidance(
        "show this as a bar chart",
        ["month", "count"],
        [["2024-01", 10], ["2024-02", 15]],
    )

    assert "line chart" in text


def test_build_visualization_guidance_rejects_too_many_categories():
    rows = [[f"segment_{i}", i + 1] for i in range(25)]
    text = build_visualization_guidance("show this as a bar chart", ["segment", "count"], rows)

    assert "25 categories" in text
    assert "top 10" in text


def test_infer_plotly_rejects_single_slice_pie_chart():
    viz = infer_plotly(
        "show me a pie chart",
        ["segment", "count"],
        [["all_clients", 5000]],
    )

    assert viz is None


def test_infer_plotly_uses_line_chart_for_generic_time_series_request():
    viz = infer_plotly(
        "plot it",
        ["month", "count"],
        [["2024-01", 10], ["2024-02", 15]],
    )

    assert viz is not None
    assert viz["figure"]["data"][0]["type"] == "scatter"
