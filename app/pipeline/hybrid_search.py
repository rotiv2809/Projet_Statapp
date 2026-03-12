import numpy
def hybrid_ranking(semantic_results, lexical_results, alpha=0.7, beta=0.3):
    # semantic_results & lexical_results = list of (question, score)
    # normaliser les scores
    sem_scores = numpy.array([s for _, s in semantic_results])
    lex_scores = numpy.array([s for _, s in lexical_results])
    sem_scores = (sem_scores - sem_scores.min()) / (sem_scores.max() - sem_scores.min() + 1e-8)
    lex_scores = (lex_scores - lex_scores.min()) / (lex_scores.max() - lex_scores.min() + 1e-8)
    
    # associer question → score final
    questions = [q for q,_ in semantic_results]
    final_scores = {}
    for i,q in enumerate(questions):
        final_scores[q] = alpha * sem_scores[i] + beta * lex_scores[i]
    # trier
    ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    return ranked