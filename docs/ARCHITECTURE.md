# StatApp Architecture Guide

This document explains how the project works end-to-end:

- runtime entry points,
- multi-agent responsibilities,
- synchronous pipeline flow,
- LangGraph flow,
- how files connect to each other,
- why each layer exists.

Diagrams are available in:
`diagrams/`

Configuration and decision tracking is in:
`CONFIG_TRACKER.md`

## 1. What This Project Does

StatApp is a Text-to-SQL assistant for a SQLite database (`clients`, `dossiers`, `transactions`).

It takes a natural-language question and returns:

- a safe SQL query,
- query results,
- a human-readable answer,
- an optional Plotly visualization.

It uses a multi-agent architecture with 5 main agents:

- `guardrails_agent`
- `sql_agent`
- `error_agent`
- `analysis_agent`
- `viz_agent`

The canonical prompt/role registry is in `app/agents/shared/config.py`.

## 2. Entry Points

### Streamlit app

File: `streamlit_app.py`

- Collects user input from chat UI.
- Calls `app.pipeline.data_pipeline.run_data_pipeline(...)`.
- Displays answer, SQL, table, and chart.

### CLI

File: `app/main.py`

- Runs one question from terminal.
- Also calls `run_data_pipeline(...)`.

Example:

```bash
python -m app.main --db data/statapp.sqlite --question "How many clients by segment?"
```

## 3. Current Runtime Flow (Synchronous)

Main orchestrator file: `app/pipeline/data_pipeline.py`
To understand the project, always look this file first.

Flow:

1. Load schema using `app/db/sqlite.py:get_schema_text`.
2. Run `GuardrailsAgent.evaluate(question)`.
3. If blocked or unclear:
   - return `OUT_OF_SCOPE` or `CLARIFY`.
4. Generate SQL with `SQLAgent.generate_sql(...)`.
5. Validate SQL with `app/safety/sql_validator.py:validate_sql`.
6. Execute SQL with `app/pipeline/execute_sql.py:execute_sql`.
7. If validate/execute fails:
   - call `ErrorAgent.repair_sql(...)`,
   - retry up to `MAX_SQL_REPAIR_ATTEMPTS`.
8. Format table/text with `app/formatters/format_response.py`.
9. Generate natural-language answer with `AnalysisAgent.summarize(...)`.
10. Generate visualization with `VizAgent.generate(...)` and fallback to `app/formatters/viz_plotly.py:infer_plotly`.
11. Return a single response dict to UI/CLI.

## 4. LangGraph Flow (Graph Runtime)

File: `app/pipeline/langgraph_flow.py`

Builder: `build_text2sql_graph(max_sql_repair_attempts=3)`

Nodes:

- `guardrails_agent`
- `sql_agent`
- `execute_sql`
- `error_agent`
- `analysis_agent`
- `viz_agent`

Edges:

- `guardrails_agent` -> conditional:
  - `in_scope` -> `sql_agent`
  - `blocked` -> `END`
- `sql_agent` -> `execute_sql`
- `execute_sql` -> conditional:
  - `success` -> `analysis_agent`
  - `retry` -> `error_agent`
  - `end` -> `END`
- `error_agent` -> `execute_sql`
- `analysis_agent` -> `viz_agent` -> `END`

Access from package:

```python
from app.pipeline import build_text2sql_graph
graph = build_text2sql_graph()
```

## 5. Multi-Agent Responsibilities

### `guardrails_agent`

File: `app/agents/guardrails/agent.py`

- Combines:
  - hard safety gate (`app/agents/guardrails/gatekeeper.py`),
  - semantic router (`app/agents/guardrails/router.py`).
- Returns `GatekeeperResult` with statuses:
  - `READY_FOR_SQL`
  - `NEEDS CLARIFICATION`
  - `OUT OF SCOPE`

### `sql_agent`

File: `app/agents/sql/agent.py`

- Converts question + schema -> SQLite `SELECT` query.
- Uses prompt from `app/agents/sql/prompt.py`.

### `error_agent`

File: `app/agents/error_agent.py`

- Repairs failed SQL based on schema + error message.
- Used only in retry loop after failed validation/execution.

### `analysis_agent`

File: `app/agents/analysis_agent.py`

- Converts result rows into concise human explanation.
- Fallback is deterministic formatter output.

### `viz_agent`

File: `app/agents/viz_agent.py`

- Generates Plotly code via LLM and executes in restricted env.
- Fallback chart inference from `app/formatters/viz_plotly.py`.

## 6. Safety Layers (Defense-in-Depth)

### Layer A: User-input safety

File: `app/agents/guardrails/gatekeeper.py`

- Blocks SQL-like input and injection markers.
- Blocks PII requests (`nom`, `prenom`, `date_naissance`).

### Layer B: SQL-output safety

File: `app/safety/sql_validator.py`

- Must start with `SELECT`.
- Single statement only.
- Blocks destructive keywords.
- Blocks PII columns.

### Layer C: Read-only database access

File: `app/db/sqlite.py`

- Uses SQLite read-only URI (`mode=ro`) by default.

## 7. Data Contracts

### Gatekeeper contract

File: `app/agents/guardrails/schemas.py`

Key model: `GatekeeperResult`

- `status`
- `parsed_intent`
- `missing_slots`
- `clarifying_questions`
- `notes`

### Pipeline response contract

From `run_data_pipeline(...)`, common keys:

- `ok`, `route`, `stage`
- `sql`
- `columns`, `rows`, `row_count`
- `answer_text`, `answer_table`
- `preview_rows`, `preview_row_count`, `total_rows`
- `viz`
- `attempts`, `retry_count`

## 8. File Connection Map

| File | Main purpose | Called by | Calls |
|---|---|---|---|
| `streamlit_app.py` | Web chat UI | user/browser | `app.pipeline.data_pipeline.run_data_pipeline` |
| `app/main.py` | CLI runner | terminal | `app.pipeline.run_data_pipeline` |
| `app/pipeline/data_pipeline.py` | sync orchestration | UI + CLI | all agents, validator, execute, formatters |
| `app/pipeline/langgraph_flow.py` | LangGraph orchestration | `app.pipeline.build_text2sql_graph` | same agents + validation/execute/format |
| `app/agents/shared/config.py` | agent role/prompt registry | all agents | none |
| `app/agents/guardrails/agent.py` | guardrail orchestration | pipelines | `app.agents.guardrails.gatekeep`, `router.route_message` |
| `app/agents/guardrails/router.py` | semantic route detection | `guardrails/agent.py` | regex rules only |
| `app/agents/sql/agent.py` | SQL generation | pipelines | `llm.factory.get_llm`, prompt template |
| `app/agents/error_agent.py` | SQL repair | pipelines | `llm.factory.get_llm`, prompt template |
| `app/agents/analysis_agent.py` | NL summary | pipelines | `llm.factory.get_llm` |
| `app/agents/viz_agent.py` | LLM chart generation | pipelines | `llm.factory.get_llm`, Plotly |
| `app/agents/guardrails/gatekeeper.py` | hard input safety | `guardrails/agent.py` | `app.agents.guardrails.schemas`, regex checks |
| `app/agents/guardrails/schemas.py` | gatekeeper result model | gatekeeper + guardrails | Pydantic |
| `app/safety/sql_validator.py` | SQL safety checks | pipelines + execute_sql wrapper | regex/token checks |
| `app/pipeline/execute_sql.py` | validate + execute SQL | pipelines | `db.run_query`, `sql_validator` |
| `app/db/sqlite.py` | schema + DB access | pipelines + scripts | sqlite3 |
| `app/formatters/format_response.py` | deterministic text/table formatting | pipelines | local helpers |
| `app/formatters/viz_plotly.py` | deterministic chart fallback | pipelines | local heuristics |
| `app/llm/factory.py` | provider/model selection | all LLM-based agents | OpenAI/Google/Ollama wrappers |

## 9. Why This Design

- Guardrails are separated from SQL generation:
  - easier to audit safety decisions.
- SQL generation is separated from SQL repair:
  - clearer failure handling and retries.
- Deterministic validators exist even with LLM agents:
  - prevents unsafe output from passing through.
- Two orchestration styles exist:
  - synchronous (`data_pipeline.py`) for current app stability,
  - LangGraph (`langgraph_flow.py`) for graph execution and observability.

## 10. Practical Trace Example

For question: `"Top 10 communes by number of clients in 2024"`

1. `streamlit_app.py` receives input.
2. `run_data_pipeline` starts.
3. `GuardrailsAgent` checks:
   - gatekeeper safety,
   - router clarity/scope.
4. `SQLAgent` generates query.
5. `validate_sql` checks query.
6. `execute_sql` runs read-only query.
7. If broken, `ErrorAgent` repairs and loop retries.
8. `AnalysisAgent` produces narrative answer.
9. `VizAgent` returns chart payload.
10. Streamlit renders message + SQL + table + chart.

## 11. Scripts and Utilities

- `scripts/build_sqlite_db.py`: builds local SQLite from CSVs.
- `scripts/sanity_checks.py`: simple relational integrity checks.
- `scripts/manual_data_pipeline_check.py`: manual pipeline run on sample questions.
- `scripts/manual_router_check.py`: manual router behavior check.
- `scripts/manual_safety_check.py`: manual gatekeeper + SQL safety check.
- `tests/`: authoritative automated pytest suite.

## 12. Notes for Further Evolution

- If you fully switch to LangGraph runtime, you can make `streamlit_app.py` call graph execution directly.
- `app/agents/guardrails/gatekeeper.py` is currently deterministic (regex-based). If you later add LLM slot-filling, keep `GatekeeperResult` as the stable output contract.
- Keep `agent_configs.py` as the single source of truth for agent roles/prompts.
