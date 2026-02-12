import json
from schemas import GatekeeperResult
from rules import REQUIRED_SLOTS_BY_INTENT
from prompts import GATEKEEPER_SYSTEM

def call_llm(messages: list[dict]) -> str:
    pass

def apply_rule_checks(res: GatekeeperResult) -> GatekeeperResult:
    intent = res.parsed_intent or ""
    required = REQUIRED_SLOTS_BY_INTENT(intent, [])
    
    missing = []
    for slot in required:
        if getattr(res, slot) in (None, "", [], {}):
            if "time_range" not in missing:
                missing.append("time_range")
    if missing:
        res.status = "NEEDS CLARIFICATION"
        res.missing_slots = sorted(set(res.missing_slots + missing)) ##
        
        if not res.claryfing_questions:
            qs = []
            if "time_range" in missing:
                qs.append("Which period do you want? (a) all of 2025 (b) a certain period (please tell the dates)")
            if "metric" in missing:
                qs.append("Which metric do you want...")
    
    return res

def gatekeep(user_question: str) -> GatekeeperResult:
    messages = [
        {"role": "system", "content": GATEKEEPER_SYSTEM},
        {"role": "user", "content": user_question},
    ]
    
    raw = call_llm(messages=messages)
    
    try:
        data = json.loads(raw)
        
    except Exception:
        data = {
            "status": "NEEDS_CLARIFICATION",
            "parsed_intent": None,
            "metric": None,
            "dimensions": [],
            "time_range": None,
            "filters": {},
            "missing_slots": ["parsed_intent"],
            "clarifying_questions": ["Você pode reformular a pergunta com mais detalhes? Ex.: métrica + período + por qual dimensão."],
            "notes": "LLM returned non-JSON."
        }
        
        res = GatekeeperResult.model_validate(data)
        res = apply_rule_checks(res)
        return res
