import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

if INDEX_NAME not in [i["name"] for i in pc.list_indexes()]:
    pc.create_index(
        name=INDEX_NAME,
        dimension=384,
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        )
    )

index = pc.Index(INDEX_NAME)

model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)

chunks = pd.read_csv(
    BASE_DIR / "data" / "processed" / "document_chunks.csv"
)

vectors = []

for _, row in chunks.iterrows():

    embedding = model.encode(
        row["chunk_text"]
    ).tolist()

    vectors.append({
        "id": row["chunk_id"],
        "values": embedding,
        "metadata": {
            "document_name": row["document_name"],
            "text": row["chunk_text"]
        }
    })

index.upsert(vectors=vectors)

print(f"Uploaded {len(vectors)} vectors.")