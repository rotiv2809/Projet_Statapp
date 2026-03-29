# Project Folder Guide

This document explains the current repository layout.

## Tree
```text
Projet_Statapp/
  app/
    __init__.py               # package entrypoint
    logging_utils.py          # structured JSON-style logging helpers
    main.py                   # CLI entrypoint (single pipeline run)
    messages.py               # centralized user-facing fallback copy
    agents/
      __init__.py
      analysis_agent.py       # NL explanation of SQL results
      error_agent.py          # SQL repair after validation/execution failures
      guardrails/
        __init__.py
        agent.py              # combines gatekeeper + router into one decision point
        gatekeeper.py         # user-input scope/safety checks
        prompts.py
        router.py             # route: REFUSE/CLARIFY/DATA/CHAT
        schemas.py
      shared/
        __init__.py
        config.py             # role + system prompt definitions for multi-agent flow
      sql/
        __init__.py
        agent.py              # SQL generation agent
        prompt.py             # SQL generation system prompt
      viz_agent.py            # LLM-driven Plotly code generation (with fallback)
    db/
      __init__.py
      sqlite.py               # schema extraction + query execution helpers
    formatters/
      __init__.py
      format_response.py      # text/table response formatting
      viz_plotly.py           # chart inference from result shape
    llm/
      __init__.py
      factory.py              # model/provider factory (OpenAI/Google/Ollama)
    pipeline/
      __init__.py
      data_pipeline.py        # guardrails -> sql -> validate/execute -> error_recovery -> analysis -> viz
      execute_sql.py          # safe SQL execution wrapper
      expert_review.py        # execute and persist expert-reviewed SQL corrections
      langgraph_flow.py       # optional LangGraph orchestration of the same agents
    safety/
      __init__.py
      sql_validator.py        # SQL safety rules (SELECT-only + PII block)
  scripts/
    __init__.py
    build_sqlite_db.py
    manual_data_pipeline_check.py
    manual_router_check.py
    manual_safety_check.py
    sanity_checks.py
  tests/
    test_data_pipeline.py
    test_expert_review.py
    test_format_response.py
    test_guardrails.py
    test_langgraph_flow.py
    test_sql_agent.py
    test_sql_validator.py
  logs/
    build_db_meta.json
  docs/
    ARCHITECTURE.md
    CONFIG_TRACKER.md          # central register of config values + reasons + change log template
    diagrams/
      README.md
      project_architecture.mmd
      project_architecture.svg
      runtime_flow.mmd
      runtime_flow.svg
    references/               # research papers and background reading
    STRUCTURE.md
  streamlit_app.py            # Streamlit UI
  requirements.txt
  README.md
```

## Folder responsibilities

- `app/`: main application code.
- `app/agents/guardrails/`: safety gating, routing, and guardrails orchestration.
- `app/agents/shared/`: shared agent configuration.
- `app/agents/sql/`: SQL generation prompt + implementation.
- `app/messages.py`: shared fallback and UI-facing copy.
- `app/logging_utils.py`: structured logging helpers and log-level setup.
- `scripts/`: local build and manual sanity checks.
- `tests/`: authoritative automated pytest suite.
- `logs/`: generated artifacts.
