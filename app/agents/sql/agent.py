"""
SQL generation agent — RAG-augmented.

Connection in flow:
- Upstream: called after guardrails allow DATA route.
- This file: retrieves similar (question, SQL) examples from the vector store,
  then converts natural-language question + schema + examples into one SQLite SELECT.
- Downstream: SQL goes to validator + execution in the pipeline.
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.shared.config import AGENT_CONFIGS
from app.agents.sql.prompt import SQL_SYSTEM_PROMPT
from app.agents.sql.retrieval import retrieve_similar_examples
from app.constants import clean_sql


class SQLAgent:
    def __init__(self):
        from app.llm.factory import get_llm

        cfg = AGENT_CONFIGS["sql_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]
        self.llm = get_llm()
        self.generate_prompt = ChatPromptTemplate.from_messages([
            ("system", SQL_SYSTEM_PROMPT),
            (
                "human",
                "SCHEMA:\n{schema}\n\n"
                "SIMILAR EXAMPLES (use as style reference, do NOT copy blindly):\n{examples}\n\n"
                "USER QUESTION:\n{question}\n\nSQL:",
            ),
        ])
        self.generate_chain = self.generate_prompt | self.llm | StrOutputParser()

    def generate_sql(self, question: str, schema_text: str) -> str:
        similar = retrieve_similar_examples(question, k=3)
        if similar:
            examples_text = "\n\n".join(
                f"Q: {e['question']}\nSQL: {e['sql']}" for e in similar
            )
        else:
            examples_text = "No examples available."

        raw = self.generate_chain.invoke({
            "question": question,
            "schema": schema_text,
            "examples": examples_text,
        })
        sql = clean_sql(raw)
        if not sql:
            raise RuntimeError("Empty SQL from model")
        return sql
