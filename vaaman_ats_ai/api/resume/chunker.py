def chunk_text(text, chunk_size=300, overlap=50):
    """
    Split text into overlapping chunks (by words)
    """
    words = text.split()
    chunks = []

    start = 0
    
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words):
            break

        start = max(0, end - overlap)

    # while start < len(words):
    #     end = start + chunk_size
    #     chunk_words = words[start:end]
    #     chunk = " ".join(chunk_words)
    #     chunks.append(chunk)

    #     start = end - overlap

    return chunks
