import faiss
import os
import json
import numpy as np

BASE_DIR = os.path.dirname(__file__)
INDEX_FILE = os.path.join(BASE_DIR, "faiss.index")
META_FILE = os.path.join(BASE_DIR, "metadata.json")

DIM = 384  # MiniLM embedding size


def load_index():
    if os.path.exists(INDEX_FILE):
        index = faiss.read_index(INDEX_FILE)
        with open(META_FILE, "r") as f:
            metadata = json.load(f)
    else:
        index = faiss.IndexFlatL2(DIM)
        metadata = []

    return index, metadata


def save_index(index, metadata):
    faiss.write_index(index, INDEX_FILE)
    with open(META_FILE, "w") as f:
        json.dump(metadata, f)


def add_embeddings(vectors, meta_items):
    """
    vectors: numpy array
    meta_items: list of dicts (same length)
    """
    index, metadata = load_index()

    index.add(np.array(vectors))
    metadata.extend(meta_items)

    save_index(index, metadata)



def search_similar(query_vector, top_k=5):
    index, metadata = load_index()

    if index.ntotal == 0:
        return []

    distances, indices = index.search(
        np.array([query_vector]), top_k
    )

    results = []
    for idx in indices[0]:
        if idx < len(metadata):
            results.append(metadata[idx])

    return results

def reset_index():
    index = faiss.IndexFlatL2(DIM)
    metadata = []
    save_index(index, metadata)