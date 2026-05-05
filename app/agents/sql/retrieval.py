"""Lightweight retrieval helpers for few-shot SQL examples.

This module intentionally avoids heavyweight vector DB dependencies.
It stores examples in a local JSON file and ranks them with a hybrid score that
combines token overlap, SQL pattern hints, fuzzy text similarity, and a
TF-IDF cosine similarity layer that correctly handles rephrased questions.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
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


# ---------------------------------------------------------------------------
# TF-IDF cosine similarity (no external deps)
# ---------------------------------------------------------------------------

_tfidf_cache: dict[str, tuple[list[dict], dict[str, float], list[dict[str, float]]]] | None = None


def _build_tfidf_index(examples: list[dict]) -> tuple[dict[str, float], list[dict[str, float]]]:
    """Build IDF table and per-example TF-IDF vectors from the example bank."""
    doc_tokens: list[Counter] = [Counter(_tokenize(str(e.get("question", "")))) for e in examples]
    n = len(doc_tokens)
    df: Counter = Counter()
    for ct in doc_tokens:
        for tok in ct:
            df[tok] += 1
    idf: dict[str, float] = {tok: math.log((n + 1) / (freq + 1)) + 1.0 for tok, freq in df.items()}
    vectors: list[dict[str, float]] = []
    for ct in doc_tokens:
        total = sum(ct.values()) or 1
        vec = {tok: (count / total) * idf.get(tok, 1.0) for tok, count in ct.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({tok: v / norm for tok, v in vec.items()})
    return idf, vectors


def _cosine(query_vec: dict[str, float], doc_vec: dict[str, float]) -> float:
    return sum(query_vec.get(tok, 0.0) * val for tok, val in doc_vec.items())


def _get_tfidf_index(examples: list[dict]):
    global _tfidf_cache
    # Invalidate cache if example set changed
    cache_key = str(len(examples))
    if _tfidf_cache is None or _tfidf_cache[0] != cache_key:
        idf, vectors = _build_tfidf_index(examples)
        _tfidf_cache = (cache_key, idf, vectors)
    return _tfidf_cache[1], _tfidf_cache[2]


def _tfidf_score(question: str, examples: list[dict]) -> list[float]:
    """Return a cosine TF-IDF score for question vs each example."""
    if not examples:
        return []
    idf, doc_vectors = _get_tfidf_index(examples)
    q_tokens = Counter(_tokenize(question))
    total = sum(q_tokens.values()) or 1
    q_vec = {tok: (count / total) * idf.get(tok, 1.0) for tok, count in q_tokens.items()}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    q_vec = {tok: v / q_norm for tok, v in q_vec.items()}
    return [_cosine(q_vec, dv) for dv in doc_vectors]


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
    """Return the top-k most relevant examples for the incoming question.

    Scoring combines:
    - Lexical token overlap + SQL pattern hints (original scoring)
    - TF-IDF cosine similarity (handles rephrased / synonym questions)
    Both are normalised and summed so neither dominates.
    """
    examples = _load_examples()
    if not examples:
        return []

    lexical_scores = [_score_example(question, e) for e in examples]
    tfidf_scores = _tfidf_score(question, examples)

    # Normalise each list to [0, 1] before combining
    max_lex = max(lexical_scores, default=1.0) or 1.0
    max_tfidf = max(tfidf_scores, default=1.0) or 1.0

    combined = [
        (lex / max_lex) + (tf / max_tfidf)
        for lex, tf in zip(lexical_scores, tfidf_scores)
    ]

    ranked = sorted(
        (
            (
                combined[i],
                {
                    "question": str(examples[i].get("question", "")),
                    "sql": str(examples[i].get("sql", "")),
                    "tags": list(examples[i].get("tags", [])),
                },
            )
            for i in range(len(examples))
        ),
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