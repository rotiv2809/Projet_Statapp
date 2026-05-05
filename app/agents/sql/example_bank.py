"""Curated few-shot examples for SQL generation."""

from __future__ import annotations

EXAMPLES: list[dict[str, object]] = [
    {
        "question": "How many clients are there in total?",
        "sql": "SELECT COUNT(*) AS nb_clients FROM clients",
        "tags": ["clients", "count"],
    },
    {
        "question": "How many clients by segment?",
        "sql": "SELECT segment_client, COUNT(*) AS nb FROM clients GROUP BY segment_client ORDER BY nb DESC",
        "tags": ["clients", "segment", "count", "group_by"],
    },
    {
        "question": "How many clients have the Carrefour loyalty card?",
        "sql": "SELECT COUNT(*) AS nb FROM clients WHERE carte_fidelite_carrefour = 1",
        "tags": ["clients", "loyalty", "count", "filter"],
    },
    {
        "question": "Average client seniority by segment",
        "sql": "SELECT segment_client, AVG(anciennete_mois) AS anciennete_moyenne FROM clients GROUP BY segment_client",
        "tags": ["clients", "segment", "average", "group_by"],
    },
    {
        "question": "Average fragility score by segment",
        "sql": "SELECT segment_client, AVG(score_client_fragile) AS score_moyen FROM clients GROUP BY segment_client",
        "tags": ["clients", "segment", "fragility", "average", "group_by"],
    },
    {
        "question": "Top 10 communes by number of clients",
        "sql": "SELECT commune, COUNT(*) AS nb FROM clients GROUP BY commune ORDER BY nb DESC LIMIT 10",
        "tags": ["clients", "commune", "count", "group_by", "topk"],
    },
    {
        "question": "How many dossiers by product type?",
        "sql": "SELECT type_produit, COUNT(*) AS nb FROM dossiers GROUP BY type_produit ORDER BY nb DESC",
        "tags": ["dossiers", "product", "count", "group_by"],
    },
    {
        "question": "Average amount of accepted dossiers",
        "sql": "SELECT AVG(montant) AS montant_moyen FROM dossiers WHERE statut_acceptation = 'ACCEPTE'",
        "tags": ["dossiers", "amount", "average", "accepted", "filter"],
    },
    {
        "question": "Acceptance rate by product type",
        "sql": "SELECT type_produit, ROUND(100.0 * SUM(CASE WHEN statut_acceptation = 'ACCEPTE' THEN 1 ELSE 0 END) / COUNT(*), 2) AS taux_acceptation FROM dossiers GROUP BY type_produit ORDER BY taux_acceptation DESC",
        "tags": ["dossiers", "acceptance", "rate", "group_by"],
    },
    {
        "question": "How many dossiers have payment incidents?",
        "sql": "SELECT COUNT(*) AS nb FROM dossiers WHERE nombre_incidents_paiement > 0",
        "tags": ["dossiers", "incidents", "count", "filter"],
    },
    {
        "question": "Total amount by subscription channel",
        "sql": "SELECT canal_souscription, SUM(montant) AS montant_total FROM dossiers GROUP BY canal_souscription ORDER BY montant_total DESC",
        "tags": ["dossiers", "channel", "amount", "sum", "group_by"],
    },
    {
        "question": "Clients with more than 5 payment incidents in total",
        "sql": "SELECT client_id, SUM(nombre_incidents_paiement) AS total_incidents FROM dossiers GROUP BY client_id HAVING total_incidents > 5 ORDER BY total_incidents DESC",
        "tags": ["dossiers", "clients", "incidents", "having", "group_by"],
    },
    {
        "question": "How many transactions by spending category?",
        "sql": "SELECT categorie_achat, COUNT(*) AS nb FROM transactions GROUP BY categorie_achat ORDER BY nb DESC",
        "tags": ["transactions", "category", "count", "group_by"],
    },
    {
        "question": "Total transaction amount by country",
        "sql": "SELECT pays, SUM(montant) AS montant_total FROM transactions GROUP BY pays ORDER BY montant_total DESC",
        "tags": ["transactions", "country", "amount", "sum", "group_by"],
    },
    {
        "question": "How many rejected transactions are there?",
        "sql": "SELECT COUNT(*) AS nb_rejetees FROM transactions WHERE statut_transaction = 'REJETEE'",
        "tags": ["transactions", "rejected", "count", "filter"],
    },
    {
        "question": "Monthly number of transactions",
        "sql": "SELECT strftime('%Y-%m', date_transaction) AS mois, COUNT(*) AS nb FROM transactions GROUP BY mois ORDER BY mois",
        "tags": ["transactions", "time", "month", "count", "group_by"],
    },
    {
        "question": "Number of transactions by hour of day",
        "sql": "SELECT strftime('%H', datetime_transaction) AS heure, COUNT(*) AS nb FROM transactions GROUP BY heure ORDER BY heure",
        "tags": ["transactions", "time", "hour", "count", "group_by"],
    },
    {
        "question": "Average transaction amount by client segment",
        "sql": "SELECT c.segment_client, AVG(t.montant) AS montant_moyen FROM transactions t JOIN clients c ON t.client_id = c.client_id GROUP BY c.segment_client",
        "tags": ["transactions", "clients", "segment", "average", "join", "group_by"],
    },
    {
        "question": "Acceptance rate of dossiers by client segment",
        "sql": "SELECT c.segment_client, ROUND(100.0 * SUM(CASE WHEN d.statut_acceptation = 'ACCEPTE' THEN 1 ELSE 0 END) / COUNT(*), 2) AS taux FROM dossiers d JOIN clients c ON d.client_id = c.client_id GROUP BY c.segment_client",
        "tags": ["dossiers", "clients", "segment", "acceptance", "join", "group_by"],
    },
    {
        "question": "Number of transactions by client segment",
        "sql": "SELECT c.segment_client, COUNT(*) AS nb_transactions FROM transactions t JOIN clients c ON t.client_id = c.client_id GROUP BY c.segment_client ORDER BY nb_transactions DESC",
        "tags": ["transactions", "clients", "segment", "count", "join", "group_by"],
    },
]