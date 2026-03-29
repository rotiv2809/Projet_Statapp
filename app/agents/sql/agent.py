"""
SQL generation agent.

Connection in flow:
- Upstream: called after guardrails allow DATA route.
- This file: converts natural-language question + schema into one SQLite SELECT SQL.
- Downstream: SQL goes to validator + execution in the pipeline.
"""

from __future__ import annotations

import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.shared.config import AGENT_CONFIGS
from app.agents.sql.prompt import SQL_SYSTEM_PROMPT

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def _clean_sql(text: str) -> str:
    if not text:
        return ""
    s = re.sub(_CODE_FENCE_RE, "", text).strip()
    lines = []
    for line in s.splitlines():
        if not line.strip() and lines:
            break
        lines.append(line)
    s = "\n".join(lines).strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


class SQLAgent:
    def __init__(self):
        from app.llm.factory import get_llm

        cfg = AGENT_CONFIGS["sql_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]
        self.llm = get_llm()
        self.generate_prompt = ChatPromptTemplate.from_messages([
            ("system", SQL_SYSTEM_PROMPT),
            ("human", "SCHEMA:\n{schema}\n\nUSER QUESTION:\n{question}\n\nSQL:"),
        ])
        self.generate_chain = self.generate_prompt | self.llm | StrOutputParser()

    def generate_sql(self, question: str, schema_text: str) -> str:
        raw = self.generate_chain.invoke({"question": question, "schema": schema_text})
        sql = _clean_sql(raw)
        if not sql:
            raise RuntimeError("Empty SQL from model")
        return sql
