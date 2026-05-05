from __future__ import annotations

from functools import lru_cache
import sqlite3
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Optional, Tuple, List


@dataclass(frozen=True)
class DBConfig:
    sqlite_path: Path
    read_only: bool = True
    timeout_s: float = 30.0


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type: str
    is_pk: bool = False


@dataclass(frozen=True)
class TableDef:
    name: str
    columns: tuple[ColumnDef, ...]


_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "by", "de", "des", "du", "for", "how", "in", "is",
    "la", "le", "les", "me", "of", "par", "show", "the", "to", "what", "with",
}
_ALIASES = {
    "accepted": "acceptance",
    "acceptation": "acceptance",
    "amount": "montant",
    "amounts": "montant",
    "applications": "dossier",
    "avg": "average",
    "canal": "channel",
    "carte": "loyalty",
    "categories": "category",
    "clients": "client",
    "communes": "commune",
    "country": "pays",
    "customers": "client",
    "dossiers": "dossier",
    "fragile": "fragility",
    "heure": "hour",
    "hours": "hour",
    "incidents": "incident",
    "loan": "dossier",
    "loans": "dossier",
    "loyalty": "carrefour",
    "payments": "payment",
    "produit": "product",
    "products": "product",
    "rejected": "reject",
    "spending": "transaction",
    "subscription": "channel",
    "transactions": "transaction",
}
_TABLE_HINTS = {
    "clients": {"client", "segment", "commune", "fragility", "score", "loyalty", "carrefour", "anciennete"},
    "dossiers": {"dossier", "product", "acceptance", "incident", "channel", "montant", "taux", "solde"},
    "transactions": {"transaction", "payment", "category", "enseigne", "pays", "carrefour", "hour", "date", "montant"},
}


def _connect(cfg: DBConfig) -> sqlite3.Connection:
    """
    Connect to SQLite
    """
    path = cfg.sqlite_path.resolve()

    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    if cfg.read_only:
        # Read-only connection
        uri = f"file:{path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=cfg.timeout_s)
    else:
        con = sqlite3.connect(str(path), timeout=cfg.timeout_s)

    # defaults
    con.row_factory = sqlite3.Row
    return con


def _normalize_token(token: str) -> str:
    token = token.lower()
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return _ALIASES.get(token, token)


def _tokenize(text: str) -> set[str]:
    return {
        normalized
        for raw in _TOKEN_RE.findall((text or "").lower())
        if (normalized := _normalize_token(raw)) not in _STOPWORDS
    }


@lru_cache(maxsize=8)
def _get_schema_snapshot(sqlite_path_str: str) -> tuple[TableDef, ...]:
    cfg = DBConfig(sqlite_path=Path(sqlite_path_str), read_only=True)
    tables: list[TableDef] = []

    with _connect(cfg) as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        )
        table_names = [r[0] for r in cur.fetchall()]

        for table_name in table_names:
            cur.execute(f"PRAGMA table_info({table_name});")
            columns = tuple(
                ColumnDef(
                    name=row["name"],
                    type=(row["type"] or "TEXT").upper(),
                    is_pk=bool(row["pk"]),
                )
                for row in cur.fetchall()
            )
            tables.append(TableDef(name=table_name, columns=columns))

    return tuple(tables)


def _format_schema_text(tables: tuple[TableDef, ...]) -> str:
    lines: list[str] = []
    for table in tables:
        col_parts = [
            f"{column.name} {column.type}" + (" PRIMARY KEY" if column.is_pk else "")
            for column in table.columns
        ]
        lines.append(f"TABLE {table.name}(" + ", ".join(col_parts) + ")")
    return "\n".join(lines)


def _infer_relationships(tables: tuple[TableDef, ...], selected_tables: set[str]) -> list[str]:
    pk_lookup = {
        column.name: table.name
        for table in tables
        for column in table.columns
        if column.is_pk
    }
    relationships: list[str] = []
    for table in tables:
        if table.name not in selected_tables:
            continue
        for column in table.columns:
            if column.is_pk:
                continue
            target_table = pk_lookup.get(column.name)
            if target_table and target_table in selected_tables and target_table != table.name:
                relationships.append(f"{table.name}.{column.name} -> {target_table}.{column.name}")
    return sorted(set(relationships))


def _score_table(question_tokens: set[str], table: TableDef) -> float:
    score = 0.0
    table_tokens = {_normalize_token(table.name.rstrip("s")), _normalize_token(table.name)}
    score += 6.0 * len(question_tokens & table_tokens)
    score += 2.0 * len(question_tokens & _TABLE_HINTS.get(table.name, set()))

    for column in table.columns:
        column_tokens = {_normalize_token(part) for part in column.name.split("_")}
        overlap = question_tokens & column_tokens
        if overlap:
            score += 3.0 * len(overlap)
        if _normalize_token(column.name) in question_tokens:
            score += 2.0

    return score


def _select_prompt_tables(tables: tuple[TableDef, ...], question: str, max_tables: int) -> tuple[TableDef, ...]:
    question_tokens = _tokenize(question)
    if not question_tokens:
        return tables

    scored = sorted(
        ((_score_table(question_tokens, table), table) for table in tables),
        key=lambda item: (item[0], item[1].name),
        reverse=True,
    )
    top_score = scored[0][0] if scored else 0.0
    score_floor = max(3.0, top_score * 0.45)
    selected = [table for score, table in scored if score > 0 and score >= score_floor][:max_tables]
    if not selected:
        return tables

    selected_names = {table.name for table in selected}
    if "segment" in question_tokens and selected_names & {"dossiers", "transactions"}:
        clients = next((table for table in tables if table.name == "clients"), None)
        if clients and clients.name not in selected_names:
            selected.append(clients)
            selected_names.add(clients.name)
    if "incident" in question_tokens and "clients" in selected_names and "dossiers" not in selected_names:
        dossiers = next((table for table in tables if table.name == "dossiers"), None)
        if dossiers:
            selected.append(dossiers)
    if any(token in question_tokens for token in {"carrefour", "loyalty"}) and "transactions" in selected_names and "clients" not in selected_names:
        clients = next((table for table in tables if table.name == "clients"), None)
        if clients:
            selected.append(clients)

    deduped: list[TableDef] = []
    seen: set[str] = set()
    for table in selected:
        if table.name not in seen:
            deduped.append(table)
            seen.add(table.name)
    return tuple(deduped[:max_tables])


def table_exists(sqlite_path: str | Path, table_name: str) -> bool:
    """
    Return True if table_name exists in sqlite_master.
    """
    cfg = DBConfig(sqlite_path=Path(sqlite_path), read_only=True)
    with _connect(cfg) as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table'
              AND name=?
              AND name NOT LIKE 'sqlite_%'
            LIMIT 1;
            """,
            (table_name,),
        )
        return cur.fetchone() is not None


def get_schema_text(sqlite_path: str | Path) -> str:
    """
    Build a schema string listing tables and columns (types + PK)
    """
    path = str(Path(sqlite_path).resolve())
    tables = _get_schema_snapshot(path)
    if not tables:
        return "No user tables found in database."
    return _format_schema_text(tables)


def get_prompt_schema_text(sqlite_path: str | Path, question: str, max_tables: int = 3) -> str:
    """Return a question-focused schema summary for prompt construction."""
    path = str(Path(sqlite_path).resolve())
    tables = _get_schema_snapshot(path)
    if not tables:
        return "No user tables found in database."

    selected = _select_prompt_tables(tables, question, max_tables=max_tables)
    lines = [_format_schema_text(selected)]
    relationships = _infer_relationships(tables, {table.name for table in selected})
    if relationships:
        lines.extend(f"RELATIONSHIP {relationship}" for relationship in relationships)
    return "\n".join(line for line in lines if line)


def run_query(
    sqlite_path: str | Path,
    sql: str,
    params: Optional[Iterable[Any]] = None,
    max_rows: Optional[int] = None,
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """
    Execute SQL and return (columns, rows).
    """
    cfg = DBConfig(sqlite_path=Path(sqlite_path), read_only=True)

    with _connect(cfg) as con:
        cur = con.cursor()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, tuple(params))

        # Cursor description gives columns for SELECT queries
        if cur.description is None:
            return [], []

        columns = [d[0] for d in cur.description]

        if max_rows is None:
            fetched = cur.fetchall()
        else:
            fetched = cur.fetchmany(max_rows)

        rows = [tuple(r) for r in fetched]
        return columns, rows
