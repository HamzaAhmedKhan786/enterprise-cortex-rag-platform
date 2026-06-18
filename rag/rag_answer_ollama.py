import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer
from ollama import chat

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
OLLAMA_MODEL = "llama3.2:3b"


@lru_cache(maxsize=1)
def get_embedding_model():
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def get_pinecone_index():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    return pc.Index(PINECONE_INDEX_NAME)


def retrieve_context(question: str, top_k: int = 3):
    model = get_embedding_model()
    index = get_pinecone_index()

    query_embedding = model.encode(question).tolist()

    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True
    )

    contexts = []
    sources = []

    for match in results["matches"]:
        metadata = match.get("metadata", {})
        text = metadata.get("text", "")
        source = metadata.get("source", "unknown")
        score = match.get("score", 0)

        contexts.append(
            f"Source: {source}\nScore: {score}\nContent: {text}"
        )
        sources.append(source)

    return "\n\n".join(contexts), list(dict.fromkeys(sources))


def ask_rag(question: str):
    context, sources = retrieve_context(question)

    prompt = f"""
You are an enterprise support assistant.

Rules:
- Answer ONLY from the provided context.
- Keep the answer concise.
- If the answer is not available in the context, say:
  "I do not know based on the provided documents."

Context:
{context}

Question:
{question}

Answer:
"""

    response = chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "user", "content": prompt}
        ],
        options={
            "temperature": 0.1,
            "num_predict": 150,
            "num_ctx": 2048
        }
    )

    answer = response["message"]["content"]
    return answer, sources


if __name__ == "__main__":
    while True:
        question = input("\nQuestion: ")

        if question.lower() == "exit":
            break

        answer, sources = ask_rag(question)

        print("\nAnswer:")
        print(answer)

        print("\nSources:")
        for source in sources:
            print("-", source)