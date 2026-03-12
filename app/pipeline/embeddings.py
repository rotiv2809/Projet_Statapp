from sentence_transformers import SentenceTransformer
import pickle

model = SentenceTransformer('all-MiniLM-L6-v2')  # petit et rapide

def generate_embeddings(questions, save_path=None):
    vectors = model.encode(questions, normalize_embeddings=True)
    emb_dict = dict(zip(questions, vectors))
    if save_path:
        with open(save_path, 'wb') as f:
            pickle.dump(emb_dict, f)
    return emb_dict