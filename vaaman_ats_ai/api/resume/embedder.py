from sentence_transformers import SentenceTransformer

# Load once (VERY IMPORTANT for performance)
_model = SentenceTransformer("all-MiniLM-L6-v2")

def embed_texts(texts: list[str]):
    """
    Convert list of texts into embeddings
    """
    return _model.encode(texts, convert_to_numpy=True)
