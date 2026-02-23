from __future__ import annotations
import re
from app.llm.factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.agents.sql_prompt import SQL_SYSTEM_PROMPT

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)

def _clean_sql(text:str) ->str:
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
        self.llm = get_llm()
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SQL_SYSTEM_PROMPT),
            ("human", "SCHEMA:\n{schema}\n\nUSER QUESTION:\n{question}\n\nSQL:")
            ])
        self.chain = self.prompt |self.llm  | StrOutputParser()
        
    def generate_sql(self, question: str, schema_text: str ) -> str:
        raw = self.chain.invoke({"question": question, "schema":schema_text})
        sql = _clean_sql(raw)
        if not sql:
            raise RuntimeError("Empty SQL From model")
        return sql