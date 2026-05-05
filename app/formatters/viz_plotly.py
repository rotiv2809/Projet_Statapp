import re
from typing import Any, Dict, Optional, Sequence

from app.constants import PII_COLUMNS
MAX_PIE_CATEGORIES = 8
MAX_BAR_CATEGORIES = 20

DATE_NAME_HINT = re.compile(r"(date|time|month|year)", re.I)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")

PIE_HINT = re.compile(r"\b(pie|share|proportion|percentage|percent|part)\b", re.I)
BAR_HINT = re.compile(r"\b(bar|column)\b", re.I)
LINE_HINT = re.compile(r"\b(line|trend)\b", re.I)
SCATTER_HINT = re.compile(r"\b(scatter)\b", re.I)
HISTOGRAM_HINT = re.compile(r"\b(histogram)\b", re.I)

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and x is not True and x is not False

def _looks_like_date(col: str, sample: Any) -> bool:
    if DATE_NAME_HINT.search(col or ""):
        return True
    if isinstance(sample, str):
        s = sample.strip()
        return bool(ISO_DATE.match(s) or ISO_MONTH.match(s))
    return False


def _is_positive_number(value: Any) -> bool:
    return _is_number(value) and float(value) > 0


def _as_rows(columns: Sequence[str], rows: Any) -> list[list[Any]]:
    if not isinstance(rows, list) or len(rows) == 0:
        return []
    if isinstance(rows[0], dict):
        cols = [str(c) for c in (columns or [])]
        return [[row.get(col) for col in cols] for row in rows]
    return [list(row) for row in rows]


def describe_result_set(columns: Sequence[str], rows: Any) -> Dict[str, Any]:
    cols = [str(c) for c in (columns or [])]
    data_rows = _as_rows(cols, rows)
    profile: Dict[str, Any] = {
        "semantic_type": "empty",
        "chart_ready": False,
        "suggested_chart": None,
        "x_column": None,
        "y_column": None,
        "category_count": len(data_rows),
        "pie_allowed": False,
        "reason": "No rows are available.",
    }

    if not cols or rows is None or not data_rows:
        return profile
    if any(c in PII_COLUMNS for c in cols):
        profile["semantic_type"] = "restricted"
        profile["reason"] = "PII columns cannot be charted."
        return profile
    if len(cols) == 1 and len(data_rows) == 1:
        profile["semantic_type"] = "scalar"
        profile["x_column"] = cols[0]
        profile["reason"] = "The result is a single scalar value."
        return profile
    if len(cols) != 2:
        profile["semantic_type"] = "table"
        profile["reason"] = "A chart needs one label column and one numeric value column."
        return profile

    x_values = [row[0] for row in data_rows]
    y_values = [row[1] for row in data_rows]
    profile["x_column"] = cols[0]
    profile["y_column"] = cols[1]

    if not all(_is_number(value) for value in y_values):
        profile["semantic_type"] = "table"
        profile["reason"] = "The second column is not numeric."
        return profile

    if _looks_like_date(cols[0], x_values[0]):
        profile["semantic_type"] = "time_series"
        profile["chart_ready"] = True
        profile["suggested_chart"] = "line chart"
        profile["reason"] = "Time series data is best shown as a line chart."
        return profile

    if _is_number(x_values[0]):
        profile["semantic_type"] = "numeric_pair"
        profile["chart_ready"] = True
        profile["suggested_chart"] = "scatter plot"
        profile["reason"] = "Two numeric columns can be shown as a scatter plot."
        return profile

    profile["semantic_type"] = "categorical_comparison"
    profile["suggested_chart"] = "bar chart"
    profile["pie_allowed"] = (
        2 <= len(x_values) <= MAX_PIE_CATEGORIES and all(_is_positive_number(value) for value in y_values)
    )
    if len(x_values) > MAX_BAR_CATEGORIES:
        profile["reason"] = "There are too many categories for a readable chart."
        return profile
    if len(x_values) < 2:
        profile["reason"] = "A category chart needs at least two categories."
        return profile
    profile["chart_ready"] = True
    profile["reason"] = "Grouped categorical data can be shown as a bar chart."
    return profile


def requested_chart_type(question: str) -> str:
    text = question or ""
    if PIE_HINT.search(text):
        return "pie chart"
    if BAR_HINT.search(text):
        return "bar chart"
    if LINE_HINT.search(text):
        return "line chart"
    if SCATTER_HINT.search(text):
        return "scatter plot"
    if HISTOGRAM_HINT.search(text):
        return "histogram"
    return "chart"


def _recommend_chart_type(columns: Sequence[str], rows: Any) -> Optional[str]:
    return describe_result_set(columns, rows).get("suggested_chart")


def supports_visualization_request(question: str, columns: Sequence[str], rows: Any) -> bool:
    profile = describe_result_set(columns, rows)
    cols = [str(c) for c in (columns or [])]
    data_rows = _as_rows(cols, rows)
    if not profile["suggested_chart"] or not cols or not data_rows:
        return False
    x_values = [row[0] for row in data_rows]

    requested = requested_chart_type(question)
    recommended = profile["suggested_chart"]

    if requested == "chart":
        return bool(profile["chart_ready"])
    if requested == "pie chart":
        return bool(profile["pie_allowed"])
    if requested == "line chart":
        return recommended == "line chart"
    if requested == "bar chart":
        return recommended == "bar chart" and len(x_values) <= MAX_BAR_CATEGORIES
    if requested == "scatter plot":
        return recommended == "scatter plot"
    if requested == "histogram":
        return False
    return bool(profile["chart_ready"])


def can_visualize(columns: Sequence[str], rows: Any) -> bool:
    return bool(describe_result_set(columns, rows).get("chart_ready"))


def build_visualization_guidance(question: str, columns: Sequence[str], rows: Any) -> str:
    chart_type = requested_chart_type(question)
    cols = [str(c) for c in (columns or [])]
    profile = describe_result_set(columns, rows)
    if profile["semantic_type"] == "scalar":
        if chart_type == "pie chart":
            return (
                "A pie chart does not fit a single total. I can plot this if you ask for "
                "clients by segment or by commune."
            )
        return (
            "This result is a single total, so there is nothing to split into a {}. "
            "Ask for grouped data such as clients by segment or by commune."
        ).format(chart_type)
    if profile["semantic_type"] == "empty":
        return (
            "There is no recent chart-ready result in memory. Ask a grouped analytics question first, "
            "such as top communes by clients in 2024."
        )
    if len(cols) > 2 or profile["semantic_type"] == "table":
        return (
            "This result has several columns, so I cannot turn it into a clear {} directly. "
            "Please ask for grouped data with one label column and one numeric value."
        ).format(chart_type)

    recommended = profile["suggested_chart"]
    data_rows = _as_rows(cols, rows)
    category_count = len(data_rows)
    if chart_type == "pie chart" and recommended == "bar chart":
        if category_count > MAX_PIE_CATEGORIES:
            return (
                "A pie chart would be hard to read with {} categories. A bar chart would be a better fit."
            ).format(category_count)
        return "A pie chart is not the best fit here. A bar chart would work better for comparing categories."
    if chart_type == "bar chart" and recommended == "line chart":
        return "A bar chart is not the best fit for a time series. A line chart would work better."
    if chart_type == "line chart" and recommended == "bar chart":
        return "A line chart is not the best fit for category comparison. A bar chart would work better."
    if chart_type == "scatter plot" and recommended == "bar chart":
        return "A scatter plot is not the best fit here. A bar chart would work better for comparing categories."
    if category_count > MAX_BAR_CATEGORIES:
        return (
            "This result has {} categories, so a chart would be crowded. Try asking for the top 10 "
            "or grouping the data by month."
        ).format(category_count)
    if recommended:
        return "That {} is not a good fit here. A {} would work better.".format(chart_type, recommended)
    return (
        "I cannot build a useful {} from that result. Please ask for grouped data, "
        "such as counts by category or values over time."
    ).format(chart_type)

def infer_plotly(question: str, columns: Sequence[str], rows: Any, max_points: int = 50) -> Optional[Dict[str, Any]]:
    cols = [str(c) for c in (columns or [])]
    profile = describe_result_set(columns, rows)
    if not cols or rows is None:
        return None
    if any(c in PII_COLUMNS for c in cols):
        return None
    if not isinstance(rows, list) or len(rows) == 0:
        return None
    if len(cols) != 2:
        return None  

    if not supports_visualization_request(question, cols, rows):
        return None

    xcol, ycol = cols[0], cols[1]
    data_rows = rows if isinstance(rows[0], dict) else [list(r) for r in rows]

    x0 = data_rows[0].get(xcol) if isinstance(data_rows[0], dict) else data_rows[0][0]
    y0 = data_rows[0].get(ycol) if isinstance(data_rows[0], dict) else data_rows[0][1]
    if not _is_number(y0):
        return None

    xs, ys = [], []
    for r in data_rows[:max_points]:
        if isinstance(r, dict):
            xs.append(r.get(xcol))
            ys.append(r.get(ycol))
        else:
            xs.append(r[0])
            ys.append(r[1])

    requested = requested_chart_type(question)
    selected = requested if requested != "chart" else profile["suggested_chart"]

    # PIE chart
    if selected == "pie chart":
        abs_ys = [abs(v) if _is_number(v) else v for v in ys]
        fig = {
            "data": [{"type": "pie", "labels": xs, "values": abs_ys}],
            "layout": {"title": f"Share of {ycol} by {xcol}"},
        }
        return {"type": "plotly", "figure": fig}

    # LINE for time
    if selected == "line chart":
        fig = {
            "data": [{"type": "scatter", "mode": "lines+markers", "x": xs, "y": ys, "name": ycol}],
            "layout": {"title": f"{ycol} over time", "xaxis": {"title": xcol}, "yaxis": {"title": ycol}},
        }
        return {"type": "plotly", "figure": fig}

    # SCATTER 
    if selected == "scatter plot":
        fig = {
            "data": [{"type": "scatter", "mode": "markers", "x": xs, "y": ys, "name": ycol}],
            "layout": {"title": f"{ycol} vs {xcol}", "xaxis": {"title": xcol}, "yaxis": {"title": ycol}},
        }
        return {"type": "plotly", "figure": fig}

    # BAR 
    fig = {
        "data": [{"type": "bar", "x": xs, "y": ys, "name": ycol}],
        "layout": {"title": f"{ycol} by {xcol}", "xaxis": {"title": xcol}, "yaxis": {"title": ycol}},
    }
    return {"type": "plotly", "figure": fig}
