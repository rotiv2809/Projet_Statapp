"""
Visualization generation agent.

Connection in flow:
- Upstream: called after analysis with executed SQL results.
- This file: asks LLM for Plotly code, executes in a restricted env, returns figure dict.
- Downstream: pipeline returns viz payload for UI chart rendering.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

import pandas as pd
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.agents.shared.config import AGENT_CONFIGS
from app.constants import strip_code_fences


class VizAgent:
    def __init__(self):
        from app.llm.factory import get_llm

        cfg = AGENT_CONFIGS["viz_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]
        self.llm = get_llm()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                (
                    "human",
                    (
                        "Question: {question}\n"
                        "Columns: {columns}\n"
                        "Rows sample: {rows}\n"
                        "Generate Plotly Python code using existing variables: df, px, go.\n"
                        "Rules:\n"
                        "- Define figure variable as fig\n"
                        "- No imports\n"
                        "- No markdown\n"
                        "- Keep to one chart and readable labels\n"
                    ),
                ),
            ]
        )
        self.chain = self.prompt | self.llm | StrOutputParser()

    def generate(
        self,
        question: str,
        columns: Sequence[str],
        rows: Any,
        fallback_viz: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(rows, list) or not rows:
            return fallback_viz

        try:
            import plotly.express as px
            import plotly.graph_objects as go
        except Exception:
            return fallback_viz

        try:
            df = pd.DataFrame(rows, columns=list(columns)) if rows and not isinstance(rows[0], dict) else pd.DataFrame(rows)
            if df.empty or len(df.columns) < 2:
                return fallback_viz

            raw = self.chain.invoke(
                {
                    "question": question,
                    "columns": list(df.columns),
                    "rows": json.dumps(df.head(20).to_dict(orient="records"), ensure_ascii=False),
                }
            )
            code = strip_code_fences(raw)
            if not code or "import " in code:
                return fallback_viz

            safe_builtins = {
                "len": len,
                "min": min,
                "max": max,
                "sum": sum,
                "sorted": sorted,
                "range": range,
                "list": list,
                "dict": dict,
                "float": float,
                "int": int,
                "str": str,
            }
            env: dict[str, Any] = {
                "__builtins__": safe_builtins,
                "df": df,
                "px": px,
                "go": go,
            }
            exec(code, env, env)  # noqa: S102 - restricted builtins sandbox
            fig = env.get("fig")
            if fig is None or not hasattr(fig, "to_dict"):
                return fallback_viz
            return {"type": "plotly", "figure": fig.to_dict()}
        except Exception:
            return fallback_viz
