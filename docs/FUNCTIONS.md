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

### `app/agents/shared/config.py`

- **`AGENT_CONFIGS`**
  - Dictionary of system prompts/roles for each agent (guardrail, sql, analysis, viz, error).

---

### `app/agents/guardrails/router.py`

- **`route_message(message: str) -> RouterDecision`**
  - Classifies user intent into `REFUSE`, `CLARIFY`, `DATA`, or `CHAT`.
  - `DATA_HINTS` covers core entity names (`clients`, `customers`, `transactions`, `payments`), metrics (`amount`, `revenue`, `average`, `sum`, `rate`), dimensions (`segment`, `commune`, `country`, `channel`, `canal`), KPIs (`taux`, `rate`, `balance`, `acceptance`), and time signals (`20XX`, `month`, `year`), in both English and French.
  - A question that matches any `DATA_HINTS` pattern is routed to `DATA`; only pure conversational input with no data signals falls back to `CHAT`.

- **`RouterDecision`**
  - Data class describing the routing decision (`route`, `reason`, `clarifying_question`).

---

### `app/agents/guardrails/agent.py`

- **`GuardrailsAgent.evaluate(question: str) -> GatekeeperResult`**
  - Combines deterministic safety gating (`app.agents.guardrails.gatekeep()`) with semantic routing (`route_message()`).
  - Returns a `GatekeeperResult` with status: `OUT OF SCOPE`, `NEEDS CLARIFICATION`, or `READY_FOR_SQL`.

---

### `app/agents/sql/agent.py`

- **`SQLAgent.generate_sql(question: str, schema_text: str) -> str`**
  - Uses an LLM to convert a natural-language question into a valid `SELECT` SQL query.
  - Retrieves top-3 few-shot examples via `retrieve_similar_examples()` (hybrid TF-IDF + lexical scoring).
  - Cleans the LLM output (removes markdown fences, trailing `;`, etc.).

- **`_clean_sql(text: str) -> str`**
  - Removes code fences and cleans up extra lines.

---

### `app/agents/sql/retrieval.py`

- **`retrieve_similar_examples(question: str, k: int = 3) -> list[dict]`**
  - Returns the top-k most relevant `{question, sql}` examples for the incoming question.
  - Scoring is a **hybrid of two layers** normalised and summed:
    1. Lexical layer: token overlap (with alias expansion) + SQL-pattern hints + `SequenceMatcher` ratio.
    2. TF-IDF cosine layer: handles rephrased questions that share few surface tokens with stored examples.
  - Examples are loaded from `data/rag_examples.json` (falling back to `example_bank.py`).

- **`add_example(question: str, sql: str) -> None`**
  - Adds or updates an example in the JSON-backed retrieval store.

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
  - Executes the generated code in a restricted sandbox (`__builtins__` limited to safe built-ins) inside a `ThreadPoolExecutor` with a **5-second timeout** — returns `fallback_viz` if the code times out or raises an exception.
  - Returns a dict `{"type": "plotly", "figure": ...}` or `fallback_viz`.

---

### `app/db/corrections.py`

- **`log_correction(db_path, question, generated_sql, corrected_sql, user) -> None`**
  - Stores an expert correction in the `corrections_log` SQLite table.

- **`fetch_similar_correction(db_path, question) -> Optional[str]`**
  - Returns the best matching corrected SQL for the given question using a **two-pass lookup**:
    1. Exact normalized-string match.
    2. Fuzzy similarity match (combined token-overlap + `SequenceMatcher` ratio) over all stored corrections — returns the best match above threshold `0.55`.
  - Returns `None` if no match meets the threshold.

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

### `app/agents/guardrails/gatekeeper.py`

- **`is_unsafe_user_input(q) -> bool`**
  - Detects SQL-like or injection-style user input (keywords & patterns).

- **`gatekeep(user_question) -> GatekeeperResult`**
  - Blocks queries containing SQL or PII requests.
  - Returns `GatekeeperResult(status=...)` used by `GuardrailsAgent`.

### `app/agents/guardrails/schemas.py`

- **`GatekeeperResult`**
  - Pydantic model for guardrails output. Fields: `status`, `parsed_intent`, `missing_slots`, `clarifying_questions`, `notes`.
  - Semantic fields (`metric`, `dimensions`, `time_range`, `filters`) have been removed — they were never populated. Semantic extraction is handled exclusively by `_extract_query_memory()` in the pipeline.

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

### `scripts/manual/data_pipeline_check.py` / `scripts/manual/router_check.py` / `scripts/manual/safety_check.py`
- Manual check scripts that:
  - run sample questions through the pipeline
  - show routing/classification decisions
  - validate SQL safety and execution
