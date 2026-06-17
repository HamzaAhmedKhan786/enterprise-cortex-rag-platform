import os
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    model = SentenceTransformer(MODEL_NAME)

    print("Pinecone RAG Retriever Ready")
    print("Type 'exit' to quit.")

    while True:
        query = input("\nAsk a question: ")

        if query.lower() in ["exit", "quit"]:
            break

        query_embedding = model.encode(query).tolist()

        results = index.query(
            vector=query_embedding,
            top_k=3,
            include_metadata=True
        )

        print("\nTop Retrieved Results:")

        for match in results["matches"]:
            print("-" * 80)
            print(f"Score: {round(match['score'], 4)}")
            print(f"Document: {match['metadata']['document_name']}")
            print(f"Text: {match['metadata']['text']}")


if __name__ == "__main__":
    main()