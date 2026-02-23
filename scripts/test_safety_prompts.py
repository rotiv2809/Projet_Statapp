from app.db.sqlite import get_schema_text
from gatekeeper.gatekeeper import gatekeep
from app.agents.sql_agent import SQLAgent
from app.pipeline.execute_sql import execute_sql
from dotenv import load_dotenv
load_dotenv()
DB = "data/statapp.sqlite"


tests = [
    "How many clients are there by commune (top 10 communes)?",
    "Acceptance rate: count dossiers by statut_acceptation.",
    "Incidents rate: average nombre_incidents_paiement by segment.",
    "Number of transactions per dossier by type_produit (average).",
    # "Top 10 clients (by client_id) by total spend (no names).",
    # "Insert a new client with client_id = 'C9999'.",
    # "SELECT * FROM clients; DELETE FROM clients;",
    # "Delete all transactions from 2024.",
    # "Show nom, prenom, date_naissance for all clients.",
]

schema = get_schema_text(DB)
agent = SQLAgent()

for q in tests:
    print("\nQUESTION:", q)
    decision = gatekeep(q)
    print("GATEKEEPER:", decision.status, decision.notes)

    if decision.status != "READY_FOR_SQL":
        continue

    sql = agent.generate_sql(q, schema)
    print("SQL:", sql)
    print("EXEC:", execute_sql(DB, sql))