from app.agents.guardrails.gatekeeper import gatekeep, is_unsafe_user_input
from app.agents.guardrails.router import route_message


def test_gatekeep_blocks_sql_like_input():
    result = gatekeep("SELECT * FROM clients")

    assert result.status == "OUT OF SCOPE"
    assert result.parsed_intent == "unsafe_sql_or_injection"


def test_gatekeep_blocks_pii_requests():
    result = gatekeep("Show nom and prenom for all clients")

    assert result.status == "OUT OF SCOPE"
    assert result.parsed_intent == "pii_request"


def test_is_unsafe_user_input_detects_injection_markers():
    assert is_unsafe_user_input("How many clients; DROP TABLE clients;")


def test_router_returns_chat_for_greeting():
    decision = route_message("hello")

    assert decision.route == "CHAT"
    assert decision.reason == "greeting"


def test_router_requests_clarification_for_incomplete_ranking_question():
    decision = route_message("Top 10 communes")

    assert decision.route == "CLARIFY"
    assert decision.reason == "ranking_missing_metric_time_range"
    assert "total amount" in (decision.clarifying_question or "")
    assert "2024" in (decision.clarifying_question or "")


def test_router_allows_complete_ranking_question():
    decision = route_message("Top 10 communes by number of clients in 2024")

    assert decision.route == "DATA"
    assert decision.reason == "ranking_complete"
