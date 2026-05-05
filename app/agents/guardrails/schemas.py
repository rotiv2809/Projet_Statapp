from typing import List, Literal, Optional

from pydantic import BaseModel, Field

GateStatus = Literal["READY_FOR_SQL", "NEEDS CLARIFICATION", "OUT OF SCOPE"]


class GatekeeperResult(BaseModel):
    """Result emitted by the guardrails layer.

    Fields that were previously declared here (metric, dimensions, time_range,
    filters) but never populated by any agent have been removed.  Semantic
    extraction is done downstream by _extract_query_memory() in the pipeline.
    """

    status: GateStatus
    parsed_intent: Optional[str] = None
    missing_slots: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
