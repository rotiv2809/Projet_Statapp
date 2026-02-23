from app.db.sqlite import run_query
DB = "data/statapp.sqlite"

checks = {
    "orphan_dossiers_client": """
        SELECT COUNT(*) AS n_orphans
        FROM dossiers d
        LEFT JOIN clients c ON c.client_id = d.client_id
        WHERE c.client_id IS NULL
    """,
    "orphan_transactions_client": """
        SELECT COUNT(*) AS n_orphans
        FROM transactions t
        LEFT JOIN clients c ON c.client_id = t.client_id
        WHERE c.client_id IS NULL
    """,
    "orphan_transactions_dossier": """
        SELECT COUNT(*) AS n_orphans
        FROM transactions t
        LEFT JOIN dossiers d ON d.dossier_id = t.dossier_id
        WHERE d.dossier_id IS NULL
    """,
}
for name, sql in checks.items():
    cols, rows = run_query(DB,sql)
    print(name, {cols[0]: rows[0][0]})