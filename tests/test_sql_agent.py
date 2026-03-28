import pytest
from app.agents.sql.agent import SQLAgent

def test_generate_sql_simple():
    agent = SQLAgent()
    schema = "CREATE TABLE clients (id INTEGER, name TEXT);"
    question = "Show all clients"
    sql = agent.generate_sql(question, schema)
    assert "SELECT" in sql and "clients" in sql
