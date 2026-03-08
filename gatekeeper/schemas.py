"""
Shared data contracts for gatekeeper and guardrails.

Connection in flow:
- Upstream: produced by gatekeeper/gatekeeper.py and guardrail_agent.py.
- This file: defines GatekeeperResult structure used to route pipeline stages.
- Downstream: consumed by data_pipeline.py and langgraph_flow.py.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

GateStatus = Literal["READY_FOR_SQL","NEEDS CLARIFICATION", "OUT OF SCOPE"]

class TimeRange(BaseModel):
    kind: Literal["year", "date_range", "relative"]
    value: str

class GatekeeperResult(BaseModel):
    status: GateStatus
    parsed_intent: Optional[str] = None  
    metric: Optional[str] = None 
    dimensions: List[str] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    missing_slots: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    claryfing_questions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @property
    def resolved_clarifying_questions(self) -> List[str]:
        if self.clarifying_questions:
            return self.clarifying_questions
        return self.claryfing_questions


    
