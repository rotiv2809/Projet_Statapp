import pytest
from app.agents.guardrails.agent import GuardrailsAgent

def test_greeting():
    ga = GuardrailsAgent()
    gk = ga.evaluate("hello")
    assert gk.parsed_intent == "greeting"
    assert gk.status == "OUT OF SCOPE"

def test_out_of_scope():
    ga = GuardrailsAgent()
    gk = ga.evaluate("tell me a joke")
    assert gk.status == "OUT OF SCOPE"
    assert gk.parsed_intent == "non_data_chat"

def test_needs_clarification():
    ga = GuardrailsAgent()
    gk = ga.evaluate("top 10 communes")
    assert gk.status == "NEEDS CLARIFICATION"
    assert gk.clarifying_questions
