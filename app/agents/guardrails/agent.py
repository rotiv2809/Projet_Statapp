"""
Guardrails orchestrator that combines deterministic policy and semantic routing.

Connection in flow:
- Upstream: instantiated by app/pipeline/data_pipeline.py and app/pipeline/langgraph_flow.py.
- This file: merges app.agents.guardrails.gatekeep() + router.route_message().
- Downstream: emits GatekeeperResult that decides OUT OF SCOPE / NEEDS CLARIFICATION / READY_FOR_SQL. ter
"""

from __future__ import annotations

import random

from app.agents.guardrails.gatekeeper import gatekeep
from app.agents.guardrails.router import route_message
from app.agents.guardrails.schemas import GatekeeperResult
from app.agents.shared.config import AGENT_CONFIGS


def _missing_slots_from_reason(reason: str) -> list[str]:
    if not reason.startswith("ranking_missing_"):
        return []
    suffix = reason.removeprefix("ranking_missing_")
    if not suffix:
        return []
    return [s for s in suffix.split("_") if s]


class GuardrailsAgent:
    """
    Orchestrates hard gatekeeper checks and routing-level semantic checks.
    """

    def __init__(self):
        cfg = AGENT_CONFIGS["guardrails_agent"]
        self.role = cfg["role"]
        self.system_prompt = cfg["system_prompt"]

    def evaluate(self, question: str) -> GatekeeperResult:
        base = gatekeep(question)
        if base.status != "READY_FOR_SQL":
            return base

        decision = route_message(question)

        if decision.route == "REFUSE":
            return GatekeeperResult(
                status="OUT OF SCOPE",
                parsed_intent=decision.reason,
                clarifying_questions=[],
                missing_slots=[],
                notes="Refused by guardrail routing.",
            )

        if decision.route == "CLARIFY":
            clarifying_questions = [decision.clarifying_question] if decision.clarifying_question else []
            return GatekeeperResult(
                status="NEEDS CLARIFICATION",
                parsed_intent="ranking_query_needs_details",
                clarifying_questions=clarifying_questions,
                missing_slots=_missing_slots_from_reason(decision.reason),
                notes=decision.reason,
            )

        if decision.route == "CHAT":
            if decision.reason == "greeting":
                return GatekeeperResult(
                    status="OUT OF SCOPE",
                    parsed_intent="greeting",
                    clarifying_questions=[],
                    missing_slots=[],
                    notes=random.choice([
                        "Hey! I'm your data assistant. Try asking: 'Top 10 communes by total amount in 2024'.",
                        "Hello! I can help you explore your data. For example: 'How many clients per segment in 2024?'",
                        "Hi there! Ask me anything about your clients, transactions, or dossiers. Example: 'Top 10 communes by number of transactions in 2024'.",
                    ]),
                )
            return GatekeeperResult(
                status="OUT OF SCOPE",
                parsed_intent="non_data_chat",
                clarifying_questions=[],
                missing_slots=[],
                notes="I'm designed for data analytics questions about clients, transactions, and dossiers. Could you rephrase your question around those topics?",
            )

        return base


# Backward-compatible alias
GuardrailAgent = GuardrailsAgent
