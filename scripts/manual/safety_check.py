"""Manual safety and SQL-generation check. Not part of the automated pytest suite."""

from dotenv import load_dotenv

load_dotenv()

from app.agents.guardrails.gatekeeper import gatekeep  # noqa: E402
from app.agents.sql.agent import SQLAgent  # noqa: E402
from app.db.sqlite import get_prompt_schema_text  # noqa: E402
from app.pipeline.execute_sql import execute_sql  # noqa: E402

DB = "data/statapp.sqlite"

tests = [
    "How many clients are there by commune (top 10 communes)?",
    "Acceptance rate: count dossiers by statut_acceptation.",
    "Incidents rate: average nombre_incidents_paiement by segment.",
    "Number of transactions per dossier by type_produit (average).",
]

schema = get_prompt_schema_text(DB, " ".join(tests))
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
