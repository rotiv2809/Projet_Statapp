# Function Reference

This document provides an overview of the core functions, classes, and entry points in the **Projet_Statapp** codebase.

> Note: This is intended as a quick reference guide to help you understand how the main components interact.

---

## 1) User Interface / UI

### `streamlit_app.py`

- **`main()`**
  - Streamlit entry point that runs the UI.
  - Initializes session history (`st.session_state.messages`).
  - Reads the user question, runs `run_data_pipeline()`, and displays the result.
  - Shows SQL, results table, CSV download, Plotly chart, and debug info.

- **`render_assistant_payload(m: dict, show_debug: bool)`**
  - Renders assistant extras (SQL, table, visualization, debug).

- **`render_plotly(viz: dict, key: str)`**
  - Renders a Plotly figure dict via `st.plotly_chart()`.

---

## 2) Agents (LLM pipeline + safety)

### `app/agents/agent_configs.py`

- **`AGENT_CONFIGS`**
  - Dictionary of system prompts/roles for each agent (guardrail, sql, analysis, viz, error).

---

### `app/agents/router_agent.py`

- **`route_message(message: str) -> RouterDecision`**
  - Classifies user intent into `REFUSE`, `CLARIFY`, `DATA`, or `CHAT`.
  - Uses regex patterns for business entities, metrics, time hints, destructive queries, and injection.

- **`RouterDecision`**
  - Data class describing the routing decision (`route`, `reason`, `clarifying_question`).

---

### `app/agents/guardrail_agent.py`

- **`GuardrailsAgent.evaluate(question: str) -> GatekeeperResult`**
  - Combines deterministic safety gating (`gatekeeper.gatekeep()`) with semantic routing (`route_message()`).
  - Returns a `GatekeeperResult` with status: `OUT_OF_SCOPE`, `NEEDS CLARIFICATION`, or `READY_FOR_SQL`.

---

### `app/agents/sql_agent.py`

- **`SQLAgent.generate_sql(question: str, schema_text: str) -> str`**
  - Uses an LLM to convert a natural-language question into a valid `SELECT` SQL query.
  - Cleans the LLM output (removes markdown fences, trailing `;`, etc.).

- **`_clean_sql(text: str) -> str`**
  - Removes code fences and cleans up extra lines.

---

### `app/agents/error_agent.py`

- **`ErrorAgent.repair_sql(question, schema_text, failed_sql, error_message) -> str`**
  - Uses an LLM to repair a broken SQL query (based on schema + error message) so execution can succeed.

- **`_clean_sql(text: str) -> str`**
  - Cleans LLM output (removes code fences + trailing semicolons).

---

### `app/agents/analysis_agent.py`

- **`AnalysisAgent.summarize(question, sql, columns, rows, fallback_text) -> str`**
  - Generates a natural language explanation of SQL results.
  - Uses the LLM to provide concise insights (trends, top values) and falls back to `fallback_text` if needed.

---

### `app/agents/viz_agent.py`

- **`VizAgent.generate(question, columns, rows, fallback_viz)`**
  - Asks the LLM to generate Plotly Python code for a chart.
  - Executes the generated code in a restricted environment and returns a dict `{"type": "plotly", "figure": ...}` or `fallback_viz`.

---

## 3) Database Access

### `app/db/sqlite.py`

- **`DBConfig`**
  - Dataclass for configuring SQLite path, read-only mode, and timeout.

- **`_connect(cfg: DBConfig)`**
  - Connects to SQLite (read-only by default) and sets `row_factory`.

- **`table_exists(sqlite_path, table_name) -> bool`**
  - Returns True if the table exists in the database schema.

- **`get_schema_text(sqlite_path) -> str`**
  - Builds a textual schema listing tables and columns (including types and PK flags) used for prompting the SQL generator.

- **`run_query(sqlite_path, sql, params=None, max_rows=None) -> (columns, rows)`**
  - Executes a SELECT query and returns column headers + rows.

---

## 4) Result Formatting

### `app/formatters/format_response.py`

- **`format_response(columns, rows, ...) -> FormattedResponse`**
  - Formats SQL results into: summary text, ASCII table preview, preview row list, and row counts.
  - Refuses queries that attempt to expose PII columns (`nom`, `prenom`, `date_naissance`).

- Helpers: `_normalize_rows`, `_ascii_table`, `_to_str`, `_shorten`.

- **`format_response_dict(columns, rows, **kwargs) -> dict`**
  - Returns the `format_response` result as a plain dict (useful for JSON output).

### `app/formatters/viz_plotly.py`

- **`infer_plotly(question, columns, rows, max_points=50) -> Optional[dict]`**
  - Generates a Plotly figure dict automatically if results are two columns.
  - Supports chart types: pie, line, scatter, bar.
  - Uses question hints (e.g., “share”, “percentage”) and heuristics for date/numeric axes.

---

## 5) Pipeline Orchestration

### `app/pipeline/data_pipeline.py`

- **`run_data_pipeline(db_path, question) -> dict`**
  - Main orchestrator called by UI (Streamlit) and CLI.
  - Steps:
    1. Load schema via `get_schema_text()`.
    2. Safety filtering via `GuardrailsAgent`.
    3. SQL generation via `SQLAgent`.
    4. SQL validation via `validate_sql()`.
    5. SQL execution via `execute_sql()`.
    6. Error recovery (repair via `ErrorAgent`) – up to 3 attempts.
    7. Result analysis via `AnalysisAgent`.
    8. Visualization generation via `VizAgent` + fallback `infer_plotly()`.
  - Returns a dict containing: `ok`, `route`, `sql`, `columns`, `rows`, `answer_text`, `viz`, `attempts`, etc.

---

### `app/pipeline/execute_sql.py`

- **`execute_sql(sqlite_path, sql, max_rows=200) -> dict`**
  - Validates and runs SQL.
  - Returns a dict: `{'ok': True, 'columns': ..., 'rows': ...}` or `{'ok': False, 'error': ..., 'sql': ...}`.

---

### `app/pipeline/langgraph_flow.py`

- **`build_text2sql_graph(max_sql_repair_attempts=3)`**
  - Builds a LangGraph workflow equivalent to the pipeline (nodes + conditional transitions).
  - Allows executing the workflow via `StateGraph` if `langgraph` is installed.

---

## 6) Safety / Validation

### `app/safety/sql_validator.py`

- **`validate_sql(sql) -> (bool, str)`**
  - Ensures the query:
    - starts with `SELECT`
    - contains no `;` or destructive keywords (`DROP`, `INSERT`, `UPDATE`, etc.)
    - does not reference PII columns (`nom`, `prenom`, `date_naissance`).
  - Returns `(True, "OKAY")` if valid, otherwise `(False, reason)`.

---

## 7) Gatekeeper (deterministic filtering before LLM)

### `gatekeeper/gatekeeper.py`

- **`is_unsafe_user_input(q) -> bool`**
  - Detects SQL-like or injection-style user input (keywords & patterns).

- **`gatekeep(user_question) -> GatekeeperResult`**
  - Blocks queries containing SQL or PII requests.
  - Returns `GatekeeperResult(status=...)` used by `GuardrailsAgent`.

### `gatekeeper/schemas.py`

- **`GatekeeperResult`**
  - Pydantic model standardizing gatekeeper results (status, intent, slots, clarifying questions).

---

## 8) Utility Scripts

### `scripts/build_sqlite_db.py`

- **`main()`**
  - Builds `data/statapp.sqlite` from CSVs (`client.csv`, `dossier.csv`, `transaction.csv`).
  - Creates indexes and writes metadata JSON with input/output hashes.

- Helpers:
  - `sha256_file(path)`
  - `read_csv_auto(path)`
  - `create_index_if_exists(cur, table, col)`

### `scripts/test_data_pipeline.py` / `scripts/test_router.py` / `scripts/test_safety_prompts.py`
- Quick test scripts that:
  - run sample questions through the pipeline
  - show routing/classification decisions
  - validate SQL safety and execution
