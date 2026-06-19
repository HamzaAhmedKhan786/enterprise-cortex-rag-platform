import sys
from pathlib import Path

import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, context_precision, faithfulness

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from rag.rag_pipeline import ask_rag


def build_eval_dataset(csv_path: Path) -> Dataset:
    df = pd.read_csv(csv_path)

    records = []

    for _, row in df.iterrows():
        question = row["question"]
        ground_truth = row["ground_truth"]

        result = ask_rag(question)

        answer = result["answer"]
        contexts = [doc["text"] for doc in result["documents"]]

        records.append(
            {
                "question": question,
                "answer": answer,
                "contexts": contexts,
                "ground_truth": ground_truth,
            }
        )

    return Dataset.from_list(records)


def main():
    dataset_path = BASE_DIR / "evaluation" / "ragas_dataset.csv"
    dataset = build_eval_dataset(dataset_path)

    result = evaluate(
        dataset=dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
        ],
    )

    print(result)


if __name__ == "__main__":
    main()