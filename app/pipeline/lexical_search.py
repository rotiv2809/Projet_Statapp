from rank_bm25 import BM25Okapi

def build_bm25_index(questions):
    tokenized = [q.lower().split() for q in questions]
    bm25 = BM25Okapi(tokenized)
    return bm25, tokenized

def search_lexical(query, bm25, tokenized_questions, top_k=5):
    query_tokens = query.lower().split()
    scores = bm25.get_scores(query_tokens)
    ranked_idx = scores.argsort()[::-1][:top_k]
    results = [(tokenized_questions[i], float(scores[i])) for i in ranked_idx]
    return results