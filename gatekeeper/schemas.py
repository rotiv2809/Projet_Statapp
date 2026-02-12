from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

GateStatus = Literal["READY_FOR_SQL","NEEDS CLARIFICATION", "OUT OF SCOPE"]

class TimeRange(BaseModel):
    kind: Literal["year", "date_range", "relative"] # basic exemple
    value: str

class GatekeeperResult(BaseModel):
    status: GateStatus
    parsed_intent: Optional[str] = None  # key word for the action
    metric: Optional[str] = None # will help identify the column
    dimensions: List[str] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    missing_slots: List[str] = Field(default_factory=list)
    claryfing_questions: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


    