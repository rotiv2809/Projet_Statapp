import faiss
import numpy 

def build_index(embeddings):
    vectors = numpy.array(list(embeddings.values())).astype('float32')
    index = faiss.IndexFlatIP(vectors.shape[1])  # similarité cosinus
    index.add(vectors)
    return index

def search_semantic(query_vec, index, embeddings, top_k=5):
    query_vec = numpy.array([query_vec]).astype('float32')
    D, I = index.search(query_vec, top_k)
    questions = list(embeddings.keys())
    results = [(questions[i], float(D[0][j])) for j,i in enumerate(I[0])]
    return results