"""Lightweight retrieval helpers for few-shot SQL examples.

This module intentionally avoids heavyweight vector DB dependencies.
It stores examples in a local JSON file and ranks them with a hybrid lexical score
based on token overlap, SQL pattern hints, and fuzzy text similarity.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from app.agents.sql.example_bank import EXAMPLES

_STORE_PATH = Path(__file__).parent.parent.parent.parent / "data" / "rag_examples.json"
_STOPWORDS = {
    "a", "an", "and", "are", "by", "count", "de", "des", "du", "for", "from",
    "how", "in", "is", "la", "le", "les", "me", "of", "par", "show", "the",
    "to", "what", "with",
}
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_ALIASES = {
    "accept": "acceptance",
    "accepted": "acceptance",
    "acceptation": "acceptance",
    "amount": "montant",
    "amounts": "montant",
    "avg": "average",
    "canal": "channel",
    "carte": "loyalty",
    "categories": "category",
    "clients": "client",
    "communes": "commune",
    "country": "pays",
    "customers": "client",
    "debit": "transaction",
    "dossiers": "dossier",
    "fragile": "fragility",
    "heure": "hour",
    "incidents": "incident",
    "loyalty": "carrefour",
    "months": "month",
    "payments": "payment",
    "produit": "product",
    "products": "product",
    "rate": "ratio",
    "rejected": "reject",
    "segment_client": "segment",
    "spending": "transaction",
    "status": "statut",
    "subscription": "channel",
    "transactions": "transaction",
}


def _normalize_token(token: str) -> str:
    token = token.lower()
    if token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return _ALIASES.get(token, token)


def _tokenize(text: str) -> set[str]:
    return {
        normalized
        for raw in _TOKEN_RE.findall((text or "").lower())
        if (normalized := _normalize_token(raw)) not in _STOPWORDS
    }


def _load_examples() -> list[dict[str, object]]:
    if _STORE_PATH.exists():
        try:
            payload = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return list(EXAMPLES)


def _score_example(question: str, example: dict[str, object]) -> float:
    query_tokens = _tokenize(question)
    example_tokens = _tokenize(str(example.get("question", "")))
    tag_tokens = {_normalize_token(str(tag)) for tag in example.get("tags", [])}

    overlap = len(query_tokens & example_tokens)
    tag_overlap = len(query_tokens & tag_tokens)
    ratio = SequenceMatcher(
        None,
        " ".join(sorted(query_tokens)),
        " ".join(sorted(example_tokens)),
    ).ratio()

    sql = str(example.get("sql", "")).lower()
    pattern_score = 0.0
    if {"segment", "client"} <= query_tokens and "join" in sql:
        pattern_score += 2.0
    if any(token in query_tokens for token in {"average", "moyenne"}) and "avg(" in sql:
        pattern_score += 1.5
    if any(token in query_tokens for token in {"total", "sum", "montant"}) and "sum(" in sql:
        pattern_score += 1.5
    if any(token in query_tokens for token in {"ratio", "rate", "taux"}) and "case when" in sql:
        pattern_score += 1.5
    if any(token in query_tokens for token in {"month", "hour", "year", "time"}) and "strftime(" in sql:
        pattern_score += 1.5
    if any(token in query_tokens for token in {"top", "highest"}) and "limit" in sql:
        pattern_score += 1.0

    return overlap * 3.0 + tag_overlap * 2.5 + ratio * 4.0 + pattern_score


def retrieve_similar_examples(question: str, k: int = 3) -> list[dict]:
    """Return the top-k most relevant examples for the incoming question."""
    examples = _load_examples()
    if not examples:
        return []

    ranked = sorted(
        ((
            _score_example(question, example),
            {
                "question": str(example.get("question", "")),
                "sql": str(example.get("sql", "")),
                "tags": list(example.get("tags", [])),
            },
        ) for example in examples),
        key=lambda item: item[0],
        reverse=True,
    )
    return [example for score, example in ranked[:k] if score > 0]


def add_example(question: str, sql: str) -> None:
    """Add or update a local example in the JSON-backed retrieval store."""
    examples = _load_examples()
    normalized_question = " ".join((question or "").strip().lower().split())
    updated = False
    for example in examples:
        if " ".join(str(example.get("question", "")).strip().lower().split()) == normalized_question:
            example["sql"] = sql
            updated = True
            break
    if not updated:
        examples.append({"question": question, "sql": sql, "tags": []})

    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")


def count_examples() -> int:
    """Return the number of available retrieval examples."""
    return len(_load_examples())