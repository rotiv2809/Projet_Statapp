from dotenv import load_dotenv
load_dotenv()
from app.pipeline.data_pipeline import run_data_pipeline

DB = "data/statapp.sqlite"

tests = [
    # # "How meany clients are there by segment_client?",
    # "How many clients are there by commune (top 10 communes)?",
    # "Delete all transactions from 2024.",
    # "Show nom, prenom, date_naissance for all clients.",
    "How many clients are there by commune (top 10 communes)?",
    # "Acceptance rate: count dossiers by statut_acceptation.",
    # "Incidents rate: average nombre_incidents_paiement by segment.",
    # "Number of transactions per dossier by type_produit (average).",
]

for q in tests:
    print("\n" + "="*90)
    print("Q:", q)
    res = run_data_pipeline(DB, q)
    print(res)

