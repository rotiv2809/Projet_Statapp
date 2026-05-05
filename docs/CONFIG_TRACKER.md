# Configuration Tracker

Purpose:
- Keep runtime configuration and policy constants in one place.
- Record why each setting exists.
- Make onboarding and review easier for teammates.

Update rule:
- Any PR that changes config/defaults should update this file in the same PR.

## 1) Environment Variables

> **Tip:** If you're adding a new env var, add it here, update `.env.example`, and document where it is used.

### 1.1 Core runtime vars

| Variable | Default / Example | Source of truth | Runtime consumer(s) | Notes |
|---|---|---|---|---|
| `LLM_PROVIDER` | `openai` | `.env` / `.env.example` | `app/llm/factory.py` | Switch provider (`openai`, `google`, `ollama`) without code edits. |
| `LLM_MODEL` | fallback `gpt-4o-mini` (default) / `.env.example` uses `gpt-5.2` | `.env` / `.env.example` | `app/llm/factory.py` | Model choice impacts quality/cost; per-environment override. |
| `LLM_TEMPERATURE` | `0` | `.env` / `.env.example` | `app/llm/factory.py` | Keeps LLM output deterministic for SQL / safety. |
| `OPENAI_API_KEY` | `YOUR_KEY_HERE` | `.env` | LangChain OpenAI client | Required when `LLM_PROVIDER=openai`. |
| `GOOGLE_API_KEY` | `YOUR_KEY_HERE` | `.env` | LangChain Google client | Required when `LLM_PROVIDER=google`. |
| `SQLITE_PATH` | `data/statapp.sqlite` | `.env` / `.env.example` | `streamlit_app.py` | Default DB path shown in Streamlit sidebar. |

### 1.2 Unwired / reserve vars (documented but not used yet)

| Variable | Default | Reason |
|---|---|---|
| `MAX_ROWS` | `200` | Intended global row cap, currently not wired into pipeline. |
| `LOG_LEVEL` | `INFO` | Reserved for future logging control. |

---

## 2) Code-level constants & policies

> These are the “hard-coded” rules that affect safety, limits, or behavior.

| Constant / Policy | Location | Current value | Purpose |
|---|---|---|---|
| `MAX_SQL_REPAIR_ATTEMPTS` | `app/pipeline/data_pipeline.py` | `3` | Prevent runaway SQL-repair cycles and bound latency/cost. |
| `_CORRECTION_MATCH_THRESHOLD` | `app/db/corrections.py` | `0.55` | Minimum fuzzy-similarity score for reusing an expert correction; below this a fresh SQL is generated. |
| `VizAgent exec timeout` | `app/agents/viz_agent.py` | `5.0 s` | Hard limit on LLM-generated Plotly code execution inside `ThreadPoolExecutor`; prevents server hangs. |
| `max_rows` default | `app/pipeline/execute_sql.py` | `200` | Caps returned rows per execution (also used by UI preview). |
| `BLOCKED_KEYWORDS` | `app/safety/sql_validator.py` | destructive SQL keywords | Enforce read-only behavior. |
| `PII_COLUMNS` | `app/safety/sql_validator.py`, `app/formatters/format_response.py`, `app/formatters/viz_plotly.py` | `nom`, `prenom`, `date_naissance` | Prevent PII exposure in query and visualization output. |
| `DATA_HINTS` | `app/agents/guardrails/router.py` | ~25 regex patterns (EN + FR) | Detects analytical intent; any match routes to `DATA`. Covers entity names, metrics, dimensions, KPIs, and time signals in English and French. |
| `FORBIDDEN_INPUT_PATTERNS` | `app/agents/guardrails/gatekeeper.py` | SQL/injection patterns | Reject unsafe user input before SQL generation. |
| `SQL_LIKE_START` | `app/agents/guardrails/gatekeeper.py` | Regex | Prevent users from entering raw SQL. |
| `PII_PATTERN` | `app/agents/guardrails/gatekeeper.py` | Regex | Prevent users from requesting PII at the prompt level. |

---

## 3) Agent configuration registry

**Source of truth:** `app/agents/shared/config.py`

Why it exists:
- Keeps prompts & roles consistent across all agents.
- Makes it easy to update prompt intent for all agents from one place.

Registered agents:
- `guardrails_agent`
- `sql_agent`
- `error_agent`
- `analysis_agent`
- `viz_agent`

---

## 4) Ownership Map

| Area | Primary file | Related files |
|---|---|---|
| LLM provider/model/temperature | `app/llm/factory.py` | `.env`, `.env.example`, all LLM-based agents |
| Input guardrails | `app/agents/guardrails/gatekeeper.py` | `app/agents/guardrails/schemas.py`, `app/agents/guardrails/agent.py`, `app/agents/guardrails/router.py` |
| SQL output safety | `app/safety/sql_validator.py` | `app/pipeline/execute_sql.py`, `app/pipeline/data_pipeline.py` |
| Retry behavior (SQL repair) | `app/pipeline/data_pipeline.py` | `app/agents/error_agent.py` |
| UI runtime defaults | `streamlit_app.py` | `.env`, `.env.example` |

---

## 5) Decision Log (fill on every config change)

| Date | Changed by | Config | Old → New | Reason | Risk | Rollback |
|---|---|---|---|---|---|---|
| _YYYY-MM-DD_ | _name_ | _var/constant_ | _x → y_ | _why_ | _impact_ | _how to revert_ |
| 2025-05-__ | team | `VizAgent exec timeout` | none → 5 s ThreadPoolExecutor | Prevent server hang from slow/malicious generated code (P1) | Low – 5 s is generous for a Plotly chart | Remove `with _ex.submit(...)` wrapper, restore bare `exec()` |
| 2025-05-__ | team | `retrieve_similar_examples` | lexical only → hybrid TF-IDF + lexical | Better few-shot recall for rephrased questions (P2) | Low – additive layer, fallback to lex score if all TF-IDF zero | Delete `_build_tfidf_index` / `_tfidf_score` helpers |
| 2025-05-__ | team | `_CORRECTION_MATCH_THRESHOLD` | exact match only → 0.55 fuzzy | Correction memory almost never fired on rephrased questions (P3) | Low – threshold tunable | Lower threshold or revert to exact-match path |
| 2025-05-__ | team | `DATA_HINTS` | 11 patterns → ~25 patterns | Refused valid analytical questions lacking exact entity names (P4) | Low – broader hints may route edge cases to DATA | Restore previous 11-pattern list |
| 2025-05-__ | team | `GatekeeperResult` schema | 9 fields → 5 fields | Removed `metric`, `dimensions`, `time_range`, `filters` — declared but never populated (P7) | Medium – any code reading those fields will get `None` / `AttributeError` | Re-add fields to `schemas.py` and restore `__all__` |
| 2025-05-__ | team | SQL dedup guard | none | Avoid identical SQL retry loop wasting LLM calls (P8) | Low – pure short-circuit optimisation | Remove `seen_sqls` check in `check_execution` |

---

## 6) Current gaps

1. `MAX_ROWS` in `.env.example` is not wired to runtime execution yet.
2. `LOG_LEVEL` in `.env.example` is not wired to runtime logging yet.
3. `LLM_MODEL` differs between `.env.example` (`gpt-5.2`) and code fallback (`gpt-4o-mini`); this is intentional per environment but should be watched.
