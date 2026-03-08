"""
Central registry of agent identity and prompts.

Connection in flow:
- Upstream: imported by each agent module during initialization.
- This file: defines AGENT_CONFIGS used by guardrails/sql/error/analysis/viz agents.
- Downstream: agents read role/system_prompt from here to keep behavior consistent.
"""

from __future__ import annotations

from typing import TypedDict


class AgentConfig(TypedDict):
    role: str
    system_prompt: str


AGENT_CONFIGS: dict[str, AgentConfig] = {
    "guardrails_agent": {
        "role": "Security and Scope Manager",
        "system_prompt": (
            "You are a strict guardrails system that filters questions to ensure they are "
            "relevant to e-commerce data analysis or identifies greetings."
        ),
    },
    "sql_agent": {
        "role": "SQL Expert",
        "system_prompt": (
            "You are a senior SQL developer specializing in e-commerce databases. "
            "Generate only valid SQLite queries without any formatting or explanation."
        ),
    },
    "analysis_agent": {
        "role": "Data Analyst",
        "system_prompt": (
            "You are a helpful data analyst that explains database query results in "
            "natural language with clear insights."
        ),
    },
    "viz_agent": {
        "role": "Visualization Specialist",
        "system_prompt": (
            "You are a data visualization expert. Generate clean, executable Plotly code "
            "without any markdown formatting or explanations."
        ),
    },
    "error_agent": {
        "role": "Error Recovery Specialist",
        "system_prompt": (
            "You diagnose and fix SQL errors with expert knowledge of database schemas "
            "and query optimization."
        ),
    },
}
