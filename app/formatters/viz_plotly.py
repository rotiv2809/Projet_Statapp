import re
from typing import Any, Dict, Optional, Sequence

PII_COLUMNS = {"nom", "prenom", "date_naissance"}

DATE_NAME_HINT = re.compile(r"(date|time|month|year)", re.I)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")

PIE_HINT = re.compile(r"\b(share|proportion|percentage|percent|part)\b", re.I)

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and x is not True and x is not False

def _looks_like_date(col: str, sample: Any) -> bool:
    if DATE_NAME_HINT.search(col or ""):
        return True
    if isinstance(sample, str):
        s = sample.strip()
        return bool(ISO_DATE.match(s) or ISO_MONTH.match(s))
    return False

def infer_plotly(question: str, columns: Sequence[str], rows: Any, max_points: int = 50) -> Optional[Dict[str, Any]]:
    cols = [str(c) for c in (columns or [])]
    if not cols or rows is None:
        return None
    if any(c in PII_COLUMNS for c in cols):
        return None
    if not isinstance(rows, list) or len(rows) == 0:
        return None
    if len(cols) != 2:
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

    is_time = _looks_like_date(xcol, xs[0])
    x_is_numeric = _is_number(xs[0])

    # PIE chart
    if PIE_HINT.search(question or "") and len(xs) <= 10 and all((v is None or v >= 0) for v in ys):
        fig = {
            "data": [{"type": "pie", "labels": xs, "values": ys}],
            "layout": {"title": f"Share of {ycol} by {xcol}"},
        }
        return {"type": "plotly", "figure": fig}

    # LINE for time
    if is_time:
        fig = {
            "data": [{"type": "scatter", "mode": "lines+markers", "x": xs, "y": ys, "name": ycol}],
            "layout": {"title": f"{ycol} over time", "xaxis": {"title": xcol}, "yaxis": {"title": ycol}},
        }
        return {"type": "plotly", "figure": fig}

    # SCATTER 
    if x_is_numeric:
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