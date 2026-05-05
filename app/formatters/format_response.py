from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import math
import re

from app.messages import (
    NO_RESULTS_MESSAGE,
    PII_EXPOSURE_REFUSAL,
    PLOT_SUGGESTION,
    format_general_results_summary,
)

from app.constants import PII_COLUMNS  # noqa: E402
YEAR_RE = re.compile(r"^\d{4}$")
DATEISH_RE = re.compile(r"^\d{4}(-\d{2}){0,2}$")
MONTH_NAME_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december)",
    re.IGNORECASE,
)


@dataclass
class FormattedResponse:
    text: str
    table: str
    preview_rows: List[List[str]]
    preview_row_count: int
    total_rows: int

def _to_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        # stable formatting
        if math.isnan(x):
            return "NaN"
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return str(x)


def _shorten(s: str, max_len: int) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _humanize_identifier(value: Any) -> str:
    return str(value).replace("_", " ").strip()


def _pluralize(label: str) -> str:
    text = _humanize_identifier(label)
    if not text:
        return "values"
    if text.endswith("s"):
        return text
    return text + "s"


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def _format_numeric(value: Any) -> str:
    number = _to_number(value)
    if number is None:
        return _to_str(value)
    if number.is_integer():
        return "{:,}".format(int(number))
    return "{:,.2f}".format(number).rstrip("0").rstrip(".")


def _looks_like_time_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(YEAR_RE.match(text) or DATEISH_RE.match(text) or MONTH_NAME_RE.match(text))


def _build_limitations_note(shown: int, total: int) -> str:
    if total > shown:
        return " I am summarizing the first {} rows out of {}.".format(shown, total)
    return ""


def _normalize_rows(columns: Sequence[str], rows: Any) -> List[List[Any]]:
    """
    Supports:
      - rows as list[tuple]
      - rows as list[list]
      - rows as list[dict] where keys match columns
    """
    if rows is None:
        return []
    if isinstance(rows, list) and len(rows) == 0:
        return []

    if isinstance(rows, list) and isinstance(rows[0], dict):
        out = []
        for r in rows:
            out.append([r.get(c) for c in columns])
        return out

    # assume list[tuple] or list[list]
    return [list(r) for r in rows]


def with_plot_suggestion(text: str) -> str:
    base = (text or "").rstrip()
    if not base:
        return PLOT_SUGGESTION.strip()
    if PLOT_SUGGESTION.strip() in base:
        return base
    return base + PLOT_SUGGESTION


def _ascii_table(columns: Sequence[str], rows: List[List[str]], max_col_width: int = 32) -> str:
    cols = [str(c) for c in columns]
    data = [cols] + rows

    widths = [len(c) for c in cols]
    for r in rows:
        for j, cell in enumerate(r):
            widths[j] = min(max(widths[j], len(cell)), max_col_width)

    def fmt_row(r: Sequence[str]) -> str:
        cells = []
        for j, cell in enumerate(r):
            cell = _shorten(cell, widths[j])
            cells.append(cell.ljust(widths[j]))
        return "| " + " | ".join(cells) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"

    lines = [sep, fmt_row(cols), sep]
    for r in rows:
        lines.append(fmt_row(r))
    lines.append(sep)
    return "\n".join(lines)


def format_response(
    columns: Sequence[str],
    rows: Any,
    *,
    max_preview_rows: int = 20,
    max_col_width: int = 32,
) -> FormattedResponse:
    cols = [str(c) for c in (columns or [])]
    if any(c in PII_COLUMNS for c in cols):
        return FormattedResponse(
            text=PII_EXPOSURE_REFUSAL,
            table="",
            preview_rows=[],
            preview_row_count=0,
            total_rows=0,
        )

    norm = _normalize_rows(cols, rows)
    total_rows = len(norm)

    # Convert preview rows to strings
    preview = norm[:max_preview_rows]
    preview_str = [[_to_str(x) for x in r] for r in preview]

    # Case A: no rows
    if total_rows == 0:
        return FormattedResponse(
            text=NO_RESULTS_MESSAGE,
            table=_ascii_table(cols, [], max_col_width=max_col_width) if cols else "",
            preview_rows=[],
            preview_row_count=0,
            total_rows=0,
        )

    # Case B: 1 value -> short natural sentence
    if len(cols) == 1 and total_rows == 1 and len(preview_str[0]) == 1:
        raw_val = preview[0][0]
        val = _format_numeric(raw_val)
        col = cols[0]
        human_col = _humanize_identifier(col)
        lowered = col.lower()
        if lowered.startswith("nombre_"):
            subject = _pluralize(lowered.removeprefix("nombre_"))
            text = "There are {} {}.".format(val, subject)
        elif lowered.startswith("count_"):
            subject = _pluralize(lowered.removeprefix("count_"))
            text = "There are {} {}.".format(val, subject)
        elif lowered in {"count", "total", "n", "value"}:
            text = "The result is {}.".format(val)
        else:
            text = "The {} is {}.".format(human_col, val)
        return FormattedResponse(
            text=text,
            table=_ascii_table(cols, preview_str, max_col_width=max_col_width),
            preview_rows=preview_str,
            preview_row_count=len(preview_str),
            total_rows=total_rows,
        )

    # Case C: 2 columns
    if len(cols) == 2:
        group_col, val_col = cols[0], cols[1]
        shown = len(preview_str)
        raw_xs = [r[0] for r in preview]
        raw_ys = [r[1] for r in preview]
        numeric_ys = [_to_number(v) for v in raw_ys]
        all_numeric = all(v is not None for v in numeric_ys)

        if all_numeric and raw_xs and _looks_like_time_value(raw_xs[0]):
            if shown >= 2 and total_rows == 2:
                points = sorted(zip(raw_xs, numeric_ys), key=lambda item: str(item[0]))
                earlier_x, earlier_y = points[0]
                later_x, later_y = points[-1]
                delta = later_y - earlier_y
                if delta > 0:
                    text = "{} is higher than {} by {}.".format(
                        later_x, earlier_x, _format_numeric(delta)
                    )
                elif delta < 0:
                    text = "{} is lower than {} by {}.".format(
                        later_x, earlier_x, _format_numeric(abs(delta))
                    )
                else:
                    text = "{} is the same as {} at {}.".format(
                        later_x, earlier_x, _format_numeric(later_y)
                    )
                text += _build_limitations_note(shown, total_rows)
            else:
                peak_index = max(range(shown), key=lambda idx: numeric_ys[idx] if numeric_ys[idx] is not None else float("-inf"))
                text = "The peak was in {} with {} {}.".format(
                    raw_xs[peak_index],
                    _format_numeric(raw_ys[peak_index]),
                    _humanize_identifier(val_col),
                )
                text += _build_limitations_note(shown, total_rows)
        elif all_numeric:
            top_items = [
                "{} ({})".format(raw_xs[idx], _format_numeric(raw_ys[idx]))
                for idx in range(min(3, shown))
            ]
            if len(top_items) == 1:
                text = "The top {} is {}.".format(
                    _humanize_identifier(group_col),
                    top_items[0],
                )
            elif len(top_items) == 2:
                text = "The top {} are {} and {}.".format(
                    _pluralize(group_col),
                    top_items[0],
                    top_items[1],
                )
            else:
                text = "The top {} are {}, {}, and {}.".format(
                    _pluralize(group_col),
                    top_items[0],
                    top_items[1],
                    top_items[2],
                )
            text += _build_limitations_note(shown, total_rows)
        else:
            lines = ["Top {} ({} -> {}):".format(shown, group_col, val_col)]
            for r in preview_str:
                lines.append(f"- {r[0]} : {r[1]}")
            if total_rows > shown:
                lines.append("(showing {}/{})".format(shown, total_rows))
            text = "\n".join(lines)
        return FormattedResponse(
            text=text,
            table=_ascii_table(cols, preview_str, max_col_width=max_col_width),
            preview_rows=preview_str,
            preview_row_count=shown,
            total_rows=total_rows,
        )

    # Case D: general table preview
    table = _ascii_table(cols, preview_str, max_col_width=max_col_width)
    text = format_general_results_summary(total_rows, len(preview_str))
    if total_rows > len(preview_str):
        text += " I may be missing details outside this preview."
    elif len(cols) > 2:
        text += " This result has several columns, so I am keeping the summary high level."

    return FormattedResponse(
        text=text,
        table=table,
        preview_rows=preview_str,
        preview_row_count=len(preview_str),
        total_rows=total_rows,
    )


def format_response_dict(columns: Sequence[str], rows: Any, **kwargs) -> Dict[str, Any]:
    fr = format_response(columns, rows, **kwargs)
    return {
        "text": fr.text,
        "table": fr.table,
        "preview_rows": fr.preview_rows,
        "preview_row_count": fr.preview_row_count,
        "total_rows": fr.total_rows,
    }
