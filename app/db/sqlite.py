from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple, List


@dataclass(frozen=True)
class DBConfig:
    sqlite_path: Path
    read_only: bool = True
    timeout_s: float = 30.0


def _connect(cfg: DBConfig) -> sqlite3.Connection:
    """
    Connect to SQLite.
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
    cfg = DBConfig(sqlite_path=Path(sqlite_path), read_only=True)
    lines: List[str] = []

    with _connect(cfg) as con:
        cur = con.cursor()

        # List tables
        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        )
        tables = [r[0] for r in cur.fetchall()]

        if not tables:
            return "No user tables found in database."

        for t in tables:
            cur.execute(f"PRAGMA table_info({t});")
            cols = cur.fetchall()
            # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk

            col_parts = []
            for c in cols:
                col_name = c["name"]
                col_type = (c["type"] or "TEXT").upper()
                is_pk = bool(c["pk"])
                col_parts.append(f"{col_name} {col_type}" + (" PRIMARY KEY" if is_pk else ""))

            lines.append(f"TABLE {t}(" + ", ".join(col_parts) + ")")

    return "\n".join(lines)


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