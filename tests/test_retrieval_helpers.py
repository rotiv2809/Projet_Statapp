import sqlite3

from app.db.sqlite import get_prompt_schema_text
from app.agents.sql.retrieval import retrieve_similar_examples


def _build_test_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE clients (client_id INTEGER PRIMARY KEY, segment_client TEXT, commune TEXT)")
    cur.execute(
        "CREATE TABLE dossiers (dossier_id INTEGER PRIMARY KEY, client_id INTEGER, statut_acceptation TEXT, nombre_incidents_paiement INTEGER)"
    )
    cur.execute(
        "CREATE TABLE transactions (transaction_id INTEGER PRIMARY KEY, client_id INTEGER, montant REAL, categorie_achat TEXT)"
    )
    conn.commit()
    conn.close()


def test_get_prompt_schema_text_focuses_on_single_table(tmp_path):
    db_path = tmp_path / "sample.sqlite"
    _build_test_db(db_path)

    schema_text = get_prompt_schema_text(db_path, "How many clients by segment?")

    assert "TABLE clients(" in schema_text
    assert "segment_client TEXT" in schema_text
    assert "TABLE transactions(" not in schema_text


def test_get_prompt_schema_text_keeps_join_context(tmp_path):
    db_path = tmp_path / "sample.sqlite"
    _build_test_db(db_path)

    schema_text = get_prompt_schema_text(db_path, "Average transaction amount by client segment")

    assert "TABLE clients(" in schema_text
    assert "TABLE transactions(" in schema_text
    assert "RELATIONSHIP transactions.client_id -> clients.client_id" in schema_text


def test_retrieve_similar_examples_prefers_matching_pattern():
    examples = retrieve_similar_examples("What is the acceptance rate by client segment?", k=2)

    assert len(examples) == 2
    assert any("JOIN clients" in example["sql"] for example in examples)
    assert any("statut_acceptation" in example["sql"] for example in examples)