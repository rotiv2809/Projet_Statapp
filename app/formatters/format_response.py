# app/formatters/format_response.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
import math

PII_COLUMNS = {"nom", "prenom", "date_naissance"}


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
            text="Refus: la requête tente d'exposer des données personnelles .",
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
            text="Aucun résultat.",
            table=_ascii_table(cols, [], max_col_width=max_col_width) if cols else "",
            preview_rows=[],
            preview_row_count=0,
            total_rows=0,
        )

    # Case B: 1 value -> dshort sentence
    if len(cols) == 1 and total_rows == 1 and len(preview_str[0]) == 1:
        val = preview_str[0][0]
        col = cols[0]
        text = f"{col} = {val}"
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
        shown = min(200, total_rows)
        lines = [f"Top {shown} ({group_col} → {val_col}) :"]
        for r in preview_str[:shown]:
            lines.append(f"- {r[0]} : {r[1]}")
        if total_rows > shown:
            lines.append(f"(affichage tronqué: {shown}/{total_rows})")
        return FormattedResponse(
            text="\n".join(lines),
            table=_ascii_table(cols, preview_str[:shown], max_col_width=max_col_width),
            preview_rows=preview_str[:shown],
            preview_row_count=shown,
            total_rows=total_rows,
        )

    # Case D: general table preview
    table = _ascii_table(cols, preview_str, max_col_width=max_col_width)
    text = f"Résultats: {total_rows} lignes. Aperçu: {len(preview_str)} lignes."
    if total_rows > len(preview_str):
        text += f" (tronqué à {len(preview_str)})"

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