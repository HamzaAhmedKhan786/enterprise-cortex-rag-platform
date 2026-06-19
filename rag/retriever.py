import os
from functools import lru_cache
from typing import Dict, List

from pinecone import Pinecone
from sentence_transformers import SentenceTransformer


EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def load_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_pinecone_index():
    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")

    if not api_key:
        raise ValueError("PINECONE_API_KEY is missing in .env")

    if not index_name:
        raise ValueError("PINECONE_INDEX_NAME is missing in .env")

    pc = Pinecone(api_key=api_key)
    return pc.Index(index_name)


def retrieve_documents(query: str, top_k: int = 3) -> List[Dict]:
    model = load_embedding_model()
    index = get_pinecone_index()

    query_embedding = model.encode(query).tolist()

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
    )

    documents = []

    for match in results.get("matches", []):
        metadata = match.get("metadata", {})

        source = (
            metadata.get("document_name")
            or metadata.get("source")
            or metadata.get("filename")
            or "unknown"
        )

        documents.append(
            {
                "source": source,
                "text": metadata.get("text", ""),
                "score": match.get("score", 0.0),
            }
        )

    return documents