import os

from ollama import chat


OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def generate_answer(prompt: str) -> str:
    response = chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        options={
            "temperature": 0.1,
            "num_predict": 150,
            "num_ctx": 2048,
        },
    )

    return response["message"]["content"]