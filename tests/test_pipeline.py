import sqlite3
import pytest
from app.pipeline.data_pipeline import run_data_pipeline

@pytest.fixture
def sample_db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE clients (id INTEGER, name TEXT);")
    conn.execute("INSERT INTO clients VALUES (1, 'Alice'), (2, 'Bob');")
    conn.commit()
    conn.close()
    return str(db_path)

def test_pipeline_returns_data(sample_db):
    result = run_data_pipeline(sample_db, "Show all clients")
    assert result["ok"]
    assert result["columns"] == ["id", "name"]
    assert len(result["rows"]) == 2

def test_empty_table(tmp_path):
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE clients (id INTEGER, name TEXT);")
    conn.commit()
    conn.close()
    result = run_data_pipeline(str(db_path), "Show all clients")
    assert result["ok"]
    assert result["columns"] == ["id", "name"]
    assert result["rows"] == []
