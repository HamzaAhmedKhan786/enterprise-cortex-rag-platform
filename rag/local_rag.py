from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


BASE_DIR = Path(__file__).resolve().parent.parent
CHUNKS_PATH = BASE_DIR / "data" / "processed" / "document_chunks.csv"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def load_chunks():
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CHUNKS_PATH}. Run: python etl/process_documents.py"
        )

    df = pd.read_csv(CHUNKS_PATH)

    if df.empty:
        raise ValueError("document_chunks.csv is empty. Check data/documents/*.txt")

    return df


def retrieve(query: str, df: pd.DataFrame, model, top_k: int = 3):
    chunk_texts = df["chunk_text"].tolist()

    chunk_embeddings = model.encode(chunk_texts)
    query_embedding = model.encode([query])

    scores = cosine_similarity(query_embedding, chunk_embeddings)[0]

    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        results.append({
            "document_name": df.iloc[idx]["document_name"],
            "chunk_id": df.iloc[idx]["chunk_id"],
            "chunk_text": df.iloc[idx]["chunk_text"],
            "score": round(float(scores[idx]), 4),
        })

    return results


def main():
    df = load_chunks()
    model = SentenceTransformer(MODEL_NAME)

    print("Local RAG Retriever Ready")
    print("Type 'exit' to quit.")

    while True:
        query = input("\nAsk a question: ")

        if query.lower() in ["exit", "quit"]:
            break

        results = retrieve(query, df, model)

        print("\nTop Retrieved Chunks:")
        for result in results:
            print("-" * 80)
            print(f"Document: {result['document_name']}")
            print(f"Chunk ID: {result['chunk_id']}")
            print(f"Score: {result['score']}")
            print(f"Text: {result['chunk_text']}")


if __name__ == "__main__":
    main()