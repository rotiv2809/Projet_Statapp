from app.safety.sql_validator import validate_sql


def test_validate_sql_accepts_safe_select():
    ok, reason = validate_sql("SELECT client_id, commune FROM clients LIMIT 10")

    assert ok is True
    assert reason == "OKAY"


def test_validate_sql_rejects_non_select():
    ok, reason = validate_sql("DELETE FROM clients")

    assert ok is False
    assert reason == "Only SELECT queries are allowed."


def test_validate_sql_rejects_multiple_statements():
    ok, reason = validate_sql("SELECT * FROM clients; SELECT * FROM dossiers")

    assert ok is False
    assert reason == "Multiple statements are not allowed."


def test_validate_sql_rejects_pii_columns():
    ok, reason = validate_sql("SELECT prenom FROM clients LIMIT 1")

    assert ok is False
    assert reason == "PII column not allowed:prenom"
