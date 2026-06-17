from pathlib import Path
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "data" / "documents"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def main():
    rows = []

    for file_path in DOCS_DIR.glob("*.txt"):
        text = file_path.read_text(encoding="utf-8")

        chunks = chunk_text(text)

        for idx, chunk in enumerate(chunks):
            rows.append({
                "document_name": file_path.name,
                "chunk_id": f"{file_path.stem}_{idx + 1}",
                "chunk_text": chunk.strip()
            })

    df = pd.DataFrame(rows)

    output_path = PROCESSED_DIR / "document_chunks.csv"
    df.to_csv(output_path, index=False, encoding="utf-8")

    print(f"Processed {len(df)} chunks")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()