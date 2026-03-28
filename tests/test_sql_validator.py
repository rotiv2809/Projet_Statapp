import sqlite3
import tempfile
from app.safety.sql_validator import validate_sql

def test_valid_select():
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as tmp:
        conn = sqlite3.connect(tmp.name)
        conn.execute("CREATE TABLE clients (id INTEGER, name TEXT);")
        conn.commit()
        conn.close()
        sql = "SELECT * FROM clients;"
        ok, reason = validate_sql(sql)
        assert ok

def test_block_drop():
    sql = "DROP TABLE clients;"
    ok, reason = validate_sql(sql)
    assert not ok
    assert "Only SELECT" in reason

def test_block_pii():
    sql = "SELECT nom, prenom FROM clients;"
    ok, reason = validate_sql(sql)
    assert not ok
    assert "PII" in reason or "not allowed" in reason