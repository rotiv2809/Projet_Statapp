# Project Folder Guide

This document explains the role of each main folder in the repository.

## `/app`
Core application package.

- `app/main.py`: Main orchestration entrypoint for the question-to-SQL pipeline.
- `app/agents/`: Agent layer responsible for routing and SQL generation prompts/logic.
- `app/pipeline/`: Execution workflow (query generation, execution, response assembly).
- `app/llm/`: LLM provider/model factory abstraction.
- `app/db/`: Database access utilities (SQLite schema loading and query execution).
- `app/formatters/`: Output formatting helpers (tabular/text and Plotly visualization utilities).
- `app/safety/`: SQL guardrails and validation rules.

## `/scripts`
Operational and validation scripts for local development.

- Database construction script from CSV sources.
- Pipeline sanity checks and focused test scripts for router/safety/data pipeline behavior.

## `/gatekeeper`
Dedicated safety/gating module used to classify or filter user requests before SQL generation.

- Includes rules, prompt templates, and schemas used by gatekeeper logic.

## `/logs`
Generated metadata/artifacts produced by build or verification scripts.

- Example: database metadata JSON emitted during data build/check steps.

## `/.git`
Git internal repository data (history, refs, hooks, objects).

## Root-level files

- `streamlit_app.py`: Streamlit frontend entrypoint.
- `requirements.txt`: Python dependencies.
- `README.md`: Setup, run, and manual test instructions.

