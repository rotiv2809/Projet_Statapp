"""
Guardrails orchestrator that combines deterministic policy and semantic routing.

Connection in flow:
- Upstream: instantiated by app/pipeline/data_pipeline.py and app/pipeline/langgraph_flow.py.
- This file: merges gatekeeper.gatekeep() + router_agent.route_message().
- Downstream: emits GatekeeperResult that decides OUT OF SCOPE / NEEDS CLARIFICATION / READY_FOR_SQL.
"""

from __future__ import annotations

from gatekeeper.gatekeeper import gatekeep
from gatekeeper.schemas import GatekeeperResult

from app.agents.agent_configs import AGENT_CONFIGS
from app.agents.router_agent import route_message


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
            return GatekeeperResult(
                status="OUT OF SCOPE",
                parsed_intent="non_data_chat",
                clarifying_questions=[],
                missing_slots=[],
                notes="This assistant handles data-related analytics questions only.",
            )

        return base


# Backward-compatible alias
GuardrailAgent = GuardrailsAgent
