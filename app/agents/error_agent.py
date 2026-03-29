"""
Error recovery agent for failed SQL.

Connection in flow:
- Upstream: called when SQL validation or execution fails.
- This file: repairs failed SQL using question + schema + error context.
- Downstream: repaired SQL is retried by the pipeline loop.
"""

from __future__ import annotations

import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.shared.config import AGENT_CONFIGS

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def _clean_sql(text: str) -> str:
    if not text:
        return ""
    s = re.sub(_CODE_FENCE_RE, "", text).strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


class ErrorAgent:
    def __init__(self):
        from app.llm.factory import get_llm

        cfg = AGENT_CONFIGS["error_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]
        self.llm = get_llm()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                (
                    "human",
                    (
                        "SCHEMA:\n{schema}\n\n"
                        "QUESTION:\n{question}\n\n"
                        "FAILED SQL:\n{failed_sql}\n\n"
                        "ERROR:\n{error}\n\n"
                        "Return ONLY corrected SQLite SELECT SQL. "
                        "No markdown, no explanations, no semicolon."
                    ),
                ),
            ]
        )
        self.chain = self.prompt | self.llm | StrOutputParser()

    def repair_sql(self, question: str, schema_text: str, failed_sql: str, error_message: str) -> str:
        raw = self.chain.invoke(
            {
                "question": question,
                "schema": schema_text,
                "failed_sql": failed_sql,
                "error": error_message,
            }
        )
        sql = _clean_sql(raw)
        if not sql:
            raise RuntimeError("Empty repaired SQL from model")
        return sql
