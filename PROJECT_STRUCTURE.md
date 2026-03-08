# Project Folder Guide

This document explains the current repository layout.

## Tree
```text
Projet_Statapp/
  app/
    __init__.py               # package entrypoint
    main.py                   # CLI entrypoint (single pipeline run)
    agents/
      __init__.py
      agent_configs.py        # role + system prompt definitions for multi-agent flow
      analysis_agent.py       # NL explanation of SQL results
      error_agent.py          # SQL repair after validation/execution failures
      guardrail_agent.py      # combines gatekeeper + router into one decision point
      router_agent.py         # route: REFUSE/CLARIFY/DATA/CHAT
      sql_agent.py            # SQL generation agent
      viz_agent.py            # LLM-driven Plotly code generation (with fallback)
      sql_prompt.py           # SQL generation system prompt
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
      langgraph_flow.py       # optional LangGraph orchestration of the same agents
    safety/
      __init__.py
      sql_validator.py        # SQL safety rules (SELECT-only + PII block)
  gatekeeper/
    __init__.py
    gatekeeper.py             # user-input scope/safety checks
    schemas.py
  scripts/
    __init__.py
    build_sqlite_db.py
    sanity_checks.py
    test_data_pipeline.py
    test_router.py
    test_safety_prompts.py
  logs/
    build_db_meta.json
  docs/
    diagrams/
      README.md
      project_architecture.mmd
      project_architecture.svg
      runtime_flow.mmd
      runtime_flow.svg
  streamlit_app.py            # Streamlit UI
  requirements.txt
  README.md
  README_ARCHITECTURE.md
  PROJECT_STRUCTURE.md
```

## Folder responsibilities

- `app/`: main application code.
- `gatekeeper/`: input-scope and safety gating before SQL generation.
- `scripts/`: local build, sanity checks, and script-style tests.
- `logs/`: generated artifacts.
