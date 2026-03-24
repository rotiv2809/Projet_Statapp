"""
Natural-language answer agent for SQL results.

Connection in flow:
- Upstream: called after successful SQL execution.
- This file: summarizes columns/rows into a concise user-facing explanation.
- Downstream: answer_text is returned to UI (Streamlit) by the pipeline.
"""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.shared.config import AGENT_CONFIGS
from app.llm.factory import get_llm


class AnalysisAgent:
    def __init__(self):
        cfg = AGENT_CONFIGS["analysis_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]
        self.llm = get_llm()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                (
                    "human",
                    (
                        "QUESTION:\n{question}\n\n"
                        "SQL:\n{sql}\n\n"
                        "COLUMNS:\n{columns}\n\n"
                        "ROWS (sample):\n{rows}\n\n"
                        "Write a concise answer in plain language. "
                        "If relevant, mention trends or top values."
                    ),
                ),
            ]
        )
        self.chain = self.prompt | self.llm | StrOutputParser()

    def summarize(
        self,
        question: str,
        sql: str,
        columns: Sequence[str],
        rows: Any,
        fallback_text: str,
    ) -> str:
        preview = rows[:30] if isinstance(rows, list) else rows
        try:
            text = self.chain.invoke(
                {
                    "question": question,
                    "sql": sql,
                    "columns": list(columns or []),
                    "rows": preview,
                }
            )
            cleaned = (text or "").strip()
            if cleaned:
                return cleaned
        except Exception:
            pass
        return fallback_text
