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


class AnalysisAgent:
    def __init__(self):
        from app.llm.factory import get_llm

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
                        "FALLBACK FACTS:\n{fallback_text}\n\n"
                        "Write a concise, natural answer that responds to the user's actual question first. "
                        "Rules:\n"
                        "- Always answer in English.\n"
                        "- Start with the answer, not a description of the table.\n"
                        "- Do not mention SQL unless the user asked for it.\n"
                        "- If the result is a single value, state it plainly.\n"
                        "- If the result is grouped, summarize the main insight and mention notable values.\n"
                        "- If the fallback facts indicate a preview, truncation, or ambiguity, mention that limitation briefly.\n"
                        "- Keep it to 1-3 short sentences."
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
                    "fallback_text": fallback_text,
                }
            )
            cleaned = (text or "").strip()
            if cleaned:
                return cleaned
        except Exception:
            pass
        return fallback_text
