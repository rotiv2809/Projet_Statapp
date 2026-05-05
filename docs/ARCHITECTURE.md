# StatApp Architecture Guide

This document explains the current system end to end:

- runtime entry points,
- the primary LangGraph flow,
- the synchronous fallback flow,
- multi-agent responsibilities,
- conversation memory and follow-up handling,
- local SQL retrieval,
- expert review and correction reuse,
- and how the main files connect together.

Diagrams are available in:
`diagrams/`

Configuration and decision tracking is in:
`CONFIG_TRACKER.md`

## 1. What This Project Does

StatApp is a Text-to-SQL assistant for a SQLite database centered on three business tables:

- `clients`
- `dossiers`
- `transactions`

For a user question, the system can produce:

- a safe SQL query,
- query results,
- a concise answer,
- a visualization,
- or a clarification / refusal when the request is unsafe or underspecified.

The canonical role and prompt registry is in `app/agents/shared/config.py`.

## 2. Entry Points

### Streamlit app

File: `streamlit_app.py`

- collects user questions from the chat UI,
- calls `app.pipeline.invoke_graph_pipeline(...)` as the primary path,
- optionally calls `app.pipeline.run_reviewed_sql(...)` when a reviewer edits the generated SQL,
- renders answer text, SQL, tabular output, CSV export, and Plotly charts.

### CLI

File: `app/main.py`

- runs one question from the terminal,
- calls `invoke_graph_pipeline(...)` with a fresh thread id,
- prints the returned payload as JSON.

Example:

```bash
python -m app.main --db data/statapp.sqlite --question "How many clients by segment?"
```

## 3. Primary Runtime Flow

Main orchestrator file: `app/pipeline/langgraph_flow.py`

This is the primary runtime used by both Streamlit and the CLI.

High-level flow:

1. `invoke_graph_pipeline(...)` receives the question and thread id.
2. Prior conversational context is loaded from LangGraph memory.
3. `context_resolver` decides whether the turn is:
   - a new analytical question,
   - a clarification reply,
   - a refinement/follow-up,
   - a chart request,
   - an explanation/simplification request,
   - or a reset/unsupported turn.
4. The prompt schema is built with `app/db/sqlite.py:get_prompt_schema_text(...)` so the model sees a focused subset of the schema.
5. `GuardrailsAgent.evaluate(...)` decides whether the request is allowed, blocked, or needs clarification.
6. The system tries to reuse expert-reviewed SQL from `corrections_log`.
7. If no reusable correction exists, `SQLAgent.generate_sql(...)` creates SQL using:
   - the focused schema,
   - the SQL system prompt,
   - local few-shot retrieval.
8. SQL is validated by `app/safety/sql_validator.py:validate_sql`.
9. SQL is executed by `app/pipeline/execute_sql.py:execute_sql`.
10. If validation or execution fails, `ErrorAgent.repair_sql(...)` enters the retry loop.
11. Results are formatted and summarized by `AnalysisAgent.summarize(...)`.
12. `VizAgent.generate(...)` produces a chart when appropriate, with deterministic fallback guidance from `app/formatters/viz_plotly.py`.
13. The final result object and conversation state are stored for future follow-up turns.

The synchronous path in `app/pipeline/data_pipeline.py` is still available as a simpler fallback orchestration path.

## 4. Graph Runtime Details

Builder: `build_text2sql_graph(max_sql_repair_attempts=3)`

Supporting runtime files:

- `app/pipeline/langgraph_flow.py`
- `app/pipeline/chatbot_orchestrator.py`
- `app/pipeline/conversation_state.py`

Core nodes:

- `context_resolver`
- `guardrails_agent`
- `sql_agent`
- `execute_sql`
- `error_agent`
- `analysis_agent`
- `viz_agent`

Node behavior summary:

- `context_resolver`
  - merges clarification replies,
  - handles chart follow-ups,
  - handles explanation/simplification follow-ups,
  - handles contextual refinements like “and for Cambodia?”.
- `guardrails_agent`
  - enforces safety/scope rules and emits routing decisions.
- `sql_agent`
  - reuses expert memory when possible,
  - otherwise generates SQL using the prompt schema and local retrieval.
- `execute_sql`
  - validates and runs SQL,
  - can fall back from bad correction-memory SQL to fresh LLM SQL.
- `error_agent`
  - repairs failed SQL and retries execution.
- `analysis_agent`
  - generates the final explanation text.
- `viz_agent`
  - generates chart payloads or chart guidance.

Main edge logic:

- `context_resolver` can short-circuit directly to `END` for pure conversational replies.
- `guardrails_agent` routes either to SQL generation or to a stop condition such as `CLARIFY` / `OUT_OF_SCOPE`.
- `execute_sql` routes either to analysis, repair, or termination depending on success/failure state.

Package access:

```python
from app.pipeline import build_text2sql_graph, invoke_graph_pipeline
```

## 5. Multi-Agent and Support Responsibilities

### `guardrails_agent`

File: `app/agents/guardrails/agent.py`

- combines the deterministic gatekeeper and the semantic router,
- returns `GatekeeperResult` with statuses:
  - `READY_FOR_SQL`
  - `NEEDS CLARIFICATION`
  - `OUT OF SCOPE`

### `sql_agent`

File: `app/agents/sql/agent.py`

- converts question + prompt schema into a SQLite `SELECT` query,
- uses prompt rules from `app/agents/sql/prompt.py`,
- uses few-shot retrieval from `app/agents/sql/retrieval.py` (hybrid TF-IDF + lexical scoring),
- uses curated examples from `app/agents/sql/example_bank.py`.

### `error_agent`

File: `app/agents/error_agent.py`

- repairs failed SQL from schema + error context,
- is only used in the retry path.

### `analysis_agent`

File: `app/agents/analysis_agent.py`

- turns rows/columns into a concise answer,
- falls back to deterministic formatter output when needed.

### `viz_agent`

File: `app/agents/viz_agent.py`

- generates Plotly output through the LLM path,
- executes LLM-generated Plotly code in a restricted sandbox with a **5-second timeout** (prevents server hang from slow or malicious generated code),
- falls back to deterministic chart inference/guidance.

### `chatbot_orchestrator`

File: `app/pipeline/chatbot_orchestrator.py`

- classifies follow-up intent,
- builds normalized analytical requests,
- decides whether a turn should reuse prior analytical context.

### `conversation_state`

File: `app/pipeline/conversation_state.py`

- stores active topic, grouping, filters, sorting, last SQL, and last result object,
- enables multi-turn follow-ups without rebuilding context from scratch.

### `expert_review`

File: `app/pipeline/expert_review.py`

- safely executes reviewer-edited SQL,
- logs expert corrections when the reviewed SQL differs from the original SQL.

## 6. Retrieval and Correction Memory

### Local SQL retrieval

Files:

- `app/agents/sql/example_bank.py`
- `app/agents/sql/retrieval.py`
- `scripts/setup/seed_sql_examples.py`

Current design:

- retrieval is local and dependency-light (no vector DB required),
- curated question→SQL examples are ranked by a **hybrid score** combining:
  - lexical token overlap and SQL-pattern hints (original layer),
  - **TF-IDF cosine similarity** (handles rephrased / synonym questions that share few surface tokens),
- both scores are normalised to `[0, 1]` and summed before top-k selection,
- examples can be written into `data/rag_examples.json` for reuse.

### Expert correction memory

Files:

- `app/db/corrections.py`
- `app/pipeline/expert_review.py`

Current design:

- expert-reviewed SQL is stored in the `corrections_log` table,
- the pipeline checks this memory before generating fresh SQL using a **two-pass lookup**:
  1. Exact normalized-string match (fastest),
  2. **Fuzzy similarity match** — scores all stored corrections using combined token-overlap + sequence-ratio similarity and returns the best match above threshold `0.55`, so rephrased questions also benefit from expert memory,
- if correction-memory SQL fails validation or execution, the runtime falls back to fresh LLM generation.

## 7. Safety Layers

### Layer A: user-input safety

File: `app/agents/guardrails/gatekeeper.py`

- blocks unsafe / out-of-scope / SQL-like requests,
- blocks PII requests such as `nom`, `prenom`, and `date_naissance`.

### Layer B: SQL-output safety

File: `app/safety/sql_validator.py`

- query must start with `SELECT`,
- only one statement is allowed,
- destructive keywords are blocked,
- PII columns are blocked.

### Layer C: read-only database access

File: `app/db/sqlite.py`

- opens SQLite with `mode=ro` by default for query execution paths.

## 8. Data Contracts

### Gatekeeper contract

File: `app/agents/guardrails/schemas.py`

Key model: `GatekeeperResult`

- `status`
- `parsed_intent`
- `missing_slots`
- `clarifying_questions`
- `notes`

> Fields `metric`, `dimensions`, `time_range`, and `filters` were removed from this model — they were declared but never populated by any agent. Semantic extraction is done exclusively by `_extract_query_memory()` in `langgraph_flow.py`.

### Pipeline response contract

Common response keys across pipeline paths:

- `ok`, `route`, `stage`
- `sql`
- `columns`, `rows`, `row_count`
- `answer_text`, `answer_table`
- `preview_rows`, `preview_row_count`, `total_rows`
- `viz`
- `attempts`, `retry_count`

> The error repair loop (`error_agent` → `execute_sql`) now short-circuits immediately if the repaired SQL is identical to one already attempted, preventing wasted LLM calls on a stuck repair cycle.

Graph-path-specific keys commonly include:

- `resolved_intent`
- `result_object`
- `conversation_state`
- `normalized_request`
- `sql_source`
- `reused_correction`

## 9. File Connection Map

| File | Main purpose | Called by | Calls |
| --- | --- | --- | --- |
| `streamlit_app.py` | Web chat UI | user/browser | `app.pipeline.invoke_graph_pipeline`, `app.pipeline.run_reviewed_sql` |
| `app/main.py` | CLI runner | terminal | `app.pipeline.invoke_graph_pipeline` |
| `app/pipeline/chatbot_orchestrator.py` | follow-up normalization | `langgraph_flow.py` | `conversation_state`, regex heuristics |
| `app/pipeline/conversation_state.py` | context/result memory helpers | `langgraph_flow.py`, `chatbot_orchestrator.py`, `expert_review.py` | local helpers |
| `app/pipeline/data_pipeline.py` | synchronous orchestration | scripts/tests/fallback runtime | all agents, validator, execute, formatters |
| `app/pipeline/langgraph_flow.py` | primary graph orchestration | UI + CLI | agents, memory helpers, validation, execution, formatters |
| `app/pipeline/expert_review.py` | reviewed SQL execution and correction logging | `streamlit_app.py` | `execute_sql`, `log_correction`, formatters |
| `app/agents/shared/config.py` | agent role/prompt registry | all agents | none |
| `app/agents/guardrails/agent.py` | guardrail orchestration | pipelines | gatekeeper, router |
| `app/agents/guardrails/router.py` | semantic route detection | `guardrails/agent.py` | regex/heuristic rules |
| `app/agents/sql/agent.py` | SQL generation | pipelines | LLM factory, prompt, retrieval |
| `app/agents/sql/retrieval.py` | local few-shot retrieval | `sql/agent.py`, setup script | `example_bank.py`, JSON store |
| `app/agents/sql/example_bank.py` | curated SQL examples | retrieval | none |
| `app/agents/error_agent.py` | SQL repair | pipelines | LLM factory |
| `app/agents/analysis_agent.py` | answer generation | pipelines | LLM factory |
| `app/agents/viz_agent.py` | chart generation | pipelines | LLM factory, Plotly |
| `app/safety/sql_validator.py` | SQL safety checks | pipelines + execute wrapper | regex/token checks |
| `app/pipeline/execute_sql.py` | safe SQL execution wrapper | pipelines | `db.run_query`, validator |
| `app/db/sqlite.py` | schema + DB access | pipelines + scripts | sqlite3 |
| `app/db/corrections.py` | expert correction storage/reuse | pipelines | sqlite3 |
| `app/formatters/format_response.py` | deterministic text/table formatting | pipelines | local helpers |
| `app/formatters/viz_plotly.py` | deterministic chart fallback | pipelines | local heuristics |
| `app/llm/factory.py` | provider/model selection | all LLM-based agents | OpenAI / Google / Ollama wrappers |

## 10. Why This Design

- Guardrails are separated from SQL generation:
  - easier to audit and evolve safety decisions.
- SQL generation is separated from SQL repair:
  - failure handling stays explicit and easier to debug.
- Follow-up normalization is separated from prompt generation:
  - conversation logic does not have to live inside the SQL prompt itself.
- Correction memory is separated from generic few-shot retrieval:
  - expert fixes and reusable examples solve different problems.
- Deterministic validation still exists even with LLM agents:
  - unsafe output cannot silently pass through.
- Two orchestration styles exist:
  - LangGraph is the primary runtime with memory,
  - the synchronous pipeline remains available as a simpler fallback.
- Prompt schema selection is question-focused:
  - smaller prompts, less schema noise, better SQL precision.

## 11. Practical Trace Example

For the question: `"Top 10 communes by number of clients in 2024"`

1. `streamlit_app.py` receives the user input.
2. `invoke_graph_pipeline(...)` starts the graph.
3. `chatbot_orchestrator` and `conversation_state` determine whether the turn is new or contextual.
4. `GuardrailsAgent` checks safety and scope.
5. `get_prompt_schema_text(...)` builds a reduced schema for the SQL prompt.
6. The pipeline checks correction memory for a prior reviewed SQL.
7. If none exists, `SQLAgent` retrieves similar examples and generates SQL.
8. `validate_sql(...)` validates the SQL.
9. `execute_sql(...)` runs the read-only query.
10. If needed, `ErrorAgent` repairs the SQL and retries.
11. `AnalysisAgent` produces the answer.
12. `VizAgent` produces a visualization payload.
13. Streamlit renders the message, SQL, table, and chart.

## 12. Scripts and Utilities

- `scripts/build_sqlite_db.py`: build local SQLite from CSV files.
- `scripts/sanity_checks.py`: basic relational/data sanity checks.
- `scripts/manual/data_pipeline_check.py`: manual pipeline run on sample questions.
- `scripts/manual/router_check.py`: manual router behavior check.
- `scripts/manual/safety_check.py`: manual gatekeeper + SQL safety check.
- `scripts/setup/seed_sql_examples.py`: seed the local SQL few-shot retrieval store.
- `tests/`: authoritative automated pytest suite.

## 13. Notes for Further Evolution

- The LangGraph runtime is the primary path used by both Streamlit and the CLI.
- `app/agents/guardrails/gatekeeper.py` is deterministic today. If you later add LLM slot-filling, keep `GatekeeperResult` as the stable output contract.
- Keep `app/agents/shared/config.py` as the single source of truth for agent roles/prompts.
- `app/constants.py` centralizes shared constants such as `PII_COLUMNS` and SQL/code-fence cleanup helpers.
