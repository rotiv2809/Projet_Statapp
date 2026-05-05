# Project Folder Guide

This document explains the current repository layout.

## Tree

```text
Projet_Statapp/
  .env.example
  EDA_StatApp.ipynb
  README.md
  app/
    __init__.py               # package entrypoint
    constants.py              # shared constants and SQL cleanup helpers
    logging_utils.py          # structured logging helpers
    main.py                   # CLI entrypoint
    messages.py               # shared user-facing messages
    agents/
      __init__.py
      analysis_agent.py       # natural-language explanation of SQL results
      error_agent.py          # SQL repair after validation/execution failures
      viz_agent.py            # Plotly generation agent with deterministic fallback
      guardrails/
        __init__.py
        agent.py              # combines gatekeeper + router into one decision point
        gatekeeper.py         # hard safety and scope checks
        prompts.py            # legacy prompt reference
        router.py             # REFUSE / CLARIFY / DATA / CHAT routing logic
        schemas.py            # gatekeeper result schema
      shared/
        __init__.py
        config.py             # role + system prompt definitions
      sql/
        __init__.py
        agent.py              # SQL generation agent
        example_bank.py       # curated question→SQL examples
        prompt.py             # SQL generation system prompt
        retrieval.py          # lightweight local retrieval for few-shot examples
    db/
      __init__.py
      corrections.py          # expert correction logging and retrieval
      sqlite.py               # schema extraction + query execution helpers
    formatters/
      __init__.py
      format_response.py      # deterministic text/table formatting
      viz_plotly.py           # chart inference / visualization guidance
    llm/
      __init__.py
      factory.py              # model/provider factory (OpenAI / Google / Ollama)
    pipeline/
      __init__.py
      chatbot_orchestrator.py # follow-up intent normalization and request shaping
      conversation_state.py   # conversation/result state helpers
      data_pipeline.py        # synchronous pipeline fallback
      execute_sql.py          # SQL validation + execution wrapper
      expert_review.py        # reviewed SQL execution and correction logging
      langgraph_flow.py       # primary LangGraph orchestration
    safety/
      __init__.py
      sql_validator.py        # SQL safety rules (SELECT-only + PII block)
  data/
    100_Questions_SQL.xlsx
    Dictionnaire_Donnees.xlsx
    client.csv
    dossier.csv
    statapp.sqlite
    transaction.csv
  docs/
    ARCHITECTURE.md
    CONFIG_TRACKER.md
    FUNCTIONS.md
    STRUCTURE.md
    diagrams/
      README.md
      project_architecture.mmd
      project_architecture.svg
      runtime_flow.mmd
      runtime_flow.svg
    references/               # research papers and background reading
  logs/
    build_db_meta.json
  scripts/
    __init__.py
    build_sqlite_db.py
    sanity_checks.py
    manual/
      data_pipeline_check.py
      router_check.py
      safety_check.py
    setup/
      seed_sql_examples.py
  streamlit_app.py            # Streamlit UI
  tests/
    fixtures/
      conversation_regressions.json
    test_conversation_regressions.py
    test_data_pipeline.py
    test_expert_review.py
    test_format_response.py
    test_guardrails.py
    test_langgraph_flow.py
    test_llm_factory.py
    test_retrieval_helpers.py
    test_sql_agent.py
    test_sql_validator.py
    test_viz_plotly.py
  pytest.ini
  requirements.txt
```

## Folder Responsibilities

- `app/`: main application package.
- `app/agents/guardrails/`: user-input safety, routing, and guardrails orchestration.
- `app/agents/sql/`: SQL generation, few-shot examples, and retrieval helpers.
- `app/pipeline/`: orchestration, conversation state, expert review, and graph runtime.
- `app/db/`: schema access and expert correction storage.
- `data/`: source CSVs, the SQLite database, and external benchmark/reference workbooks.
- `scripts/manual/`: exploratory manual checks not used by pytest.
- `scripts/setup/`: one-time setup/bootstrap helpers.
- `tests/`: authoritative automated pytest suite.
- `docs/`: architecture, structure, and configuration documentation.
- `logs/`: generated artifacts.
