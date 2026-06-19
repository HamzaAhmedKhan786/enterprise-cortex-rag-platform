import os
from typing import Dict, List

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from rag.retriever import retrieve_documents
from rag.langsmith_config import enable_langsmith

load_dotenv()
enable_langsmith()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

PROMPT = ChatPromptTemplate.from_template("""
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
""")


def build_context(documents: List[Dict]) -> str:
    return "\n\n".join(
        [
            f"Source: {doc['source']}\n"
            f"Score: {round(doc['score'], 4)}\n"
            f"Content: {doc['text']}"
            for doc in documents
        ]
    )


def ask_langchain_rag(question: str, top_k: int = 3) -> Dict:
    documents = retrieve_documents(question, top_k=top_k)

    if not documents:
        return {
            "answer": "I do not know based on the provided documents.",
            "sources": [],
            "documents": [],
        }

    context = build_context(documents)

    llm = ChatOllama(
        model=OLLAMA_MODEL,
        temperature=0.1,
        num_predict=150,
    )

    chain = PROMPT | llm
    response = chain.invoke({"context": context, "question": question})

    return {
        "answer": response.content,
        "sources": list(dict.fromkeys([doc["source"] for doc in documents])),
        "documents": documents,
    }