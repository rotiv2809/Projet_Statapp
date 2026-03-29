from app.agents.sql.agent import _clean_sql


def test_clean_sql_strips_markdown_and_trailing_semicolon():
    raw = "```sql\nSELECT client_id, commune FROM clients LIMIT 10;\n```"

    assert _clean_sql(raw) == "SELECT client_id, commune FROM clients LIMIT 10"


def test_clean_sql_stops_at_first_blank_line():
    raw = "SELECT client_id FROM clients\n\nExtra explanation that should be ignored"

    assert _clean_sql(raw) == "SELECT client_id FROM clients"
