from typing import Dict, List

from rag.ollama_llm import generate_answer
from rag.retriever import retrieve_documents


def build_context(documents: List[Dict]) -> str:
    context_parts = []

    for doc in documents:
        context_parts.append(
            f"Source: {doc['source']}\n"
            f"Score: {round(doc['score'], 4)}\n"
            f"Content: {doc['text']}"
        )

    return "\n\n".join(context_parts)


def build_prompt(question: str, context: str) -> str:
    return f"""
You are an enterprise support assistant.

Rules:
- Answer ONLY from the provided context.
- Keep the answer concise.
- Do not invent information.
- If the answer is not in the context, say:
  "I do not know based on the provided documents."

Context:
{context}

Question:
{question}

Answer:
"""


def ask_rag(question: str, top_k: int = 3) -> Dict:
    documents = retrieve_documents(question, top_k=top_k)

    if not documents:
        return {
            "answer": "I do not know based on the provided documents.",
            "sources": [],
            "documents": [],
        }

    context = build_context(documents)
    prompt = build_prompt(question, context)

    answer = generate_answer(prompt)
    sources = list(dict.fromkeys([doc["source"] for doc in documents]))

    return {
        "answer": answer,
        "sources": sources,
        "documents": documents,
    }