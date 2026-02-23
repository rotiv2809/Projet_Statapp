"""
Supabase database connector.
Uses the supabase-py client to run raw SQL via the Postgres connection.
Falls back to the PostgREST REST API for schema introspection.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from supabase import create_client, Client


def _get_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in your .env file."
        )
    return create_client(url, key)


def get_schema_text() -> str:
    """
    Introspect tables and columns from Supabase via information_schema.
    Returns the same format as the SQLite version so the SQL agent works unchanged.
    """
    client = _get_client()

    # Query information_schema via rpc or raw SQL
    result = client.rpc(
        "get_schema_info", {}
    ).execute()

    # If you don't have the RPC function, we fall back to a direct query
    # using postgrest on information_schema (may not be exposed by default).
    # So we use the execute_raw approach instead:
    cols_result = _run_raw_sql(
        """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
    )

    columns_data, rows = cols_result
    if not rows:
        return "No user tables found in database."

    tables: dict[str, list[str]] = {}
    for row in rows:
        tbl = row[0]
        col = row[1]
        dtype = row[2].upper()
        tables.setdefault(tbl, []).append(f"{col} {dtype}")

    lines = [f"TABLE {tbl}(" + ", ".join(cols) + ")" for tbl, cols in tables.items()]
    return "\n".join(lines)


def _run_raw_sql(
    sql: str,
    max_rows: Optional[int] = None,
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """
    Execute raw SQL against Supabase using the pg-meta / sql RPC endpoint.
    Supabase exposes a `query` RPC in supabase-py v2 via client.postgrest.
    We use `client.rpc` with a helper function OR the direct REST SQL endpoint.
    """
    client = _get_client()

    # supabase-py v2 allows raw SQL via the `query` method on the underlying
    # postgres client when using the service role key.
    # The cleanest approach: call the REST /rest/v1/rpc/run_sql endpoint
    # that you define in Supabase (see README note), OR use psycopg2 directly
    # via the Supabase DB connection string.

    # We use psycopg2 with the Supabase Postgres direct connection URL.
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL must be set in your .env file.\n"
            "Format: postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"
        )

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            if cur.description is None:
                return [], []
            col_names = [desc.name for desc in cur.description]
            if max_rows is not None:
                fetched = cur.fetchmany(max_rows)
            else:
                fetched = cur.fetchall()
            rows = [tuple(row[c] for c in col_names) for row in fetched]
            return col_names, rows
    finally:
        conn.close()


def run_query(
    sql: str,
    max_rows: Optional[int] = None,
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """
    Public interface: execute a SELECT query and return (columns, rows).
    """
    return _run_raw_sql(sql, max_rows=max_rows)
