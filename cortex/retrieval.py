"""Workspace-scoped BM25, parent context, and optional local dense hybrid search."""
import json
import math
import re
import time
from collections import Counter
from functools import lru_cache

from cortex import store

STRATEGIES = {"bm25": "BM25 · offline baseline", "parent_child": "Parent–child · paragraph context", "hybrid": "Hybrid · local dense + BM25 + RRF"}
STOP = {"a", "an", "the", "is", "are", "what", "how", "does", "do", "of", "to", "and", "in", "it", "i", "can", "my", "for", "on"}


def tokens(text):
    return [t for t in re.findall(r"\w+", text.lower()) if t not in STOP]


def chunk_document(text, size=800, overlap=120):
    if size <= overlap or overlap < 0:
        raise ValueError("Chunk size must exceed overlap.")
    chunks = []
    for parent in re.split(r"\n\s*\n", text):
        parent = parent.strip()
        if not parent:
            continue
        for start in range(0, len(parent), size - overlap):
            chunks.append((parent[start:start + size], parent[max(0, start - 800):start + size + 800]))
    return chunks


@lru_cache(maxsize=1)
def embedding_model():
    # Never download a model or send document contents to a model host implicitly.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", local_files_only=True)


def build_index(owner, dataset_id, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("Unsupported retrieval strategy.")
    item = store.dataset(owner, dataset_id)
    with store.connection() as db:
        db.execute("UPDATE datasets SET status='indexing',error='' WHERE id=? AND owner=?", (dataset_id, owner))
    store.audit(owner, "index_started", dataset_id, {"strategy": strategy})
    try:
        if item["kind"] == "document":
            chunks = chunk_document(item["payload"]["text"])
        else:
            # A bounded descriptive index over the same source, not a substitute
            # for exact full-table analytics. No sampling is represented as full coverage.
            rows = item["payload"]["rows"]
            if len(rows) > 2000:
                raise ValueError("Table RAG is limited to 2,000 records. Analytics still uses up to 50,000; upload a smaller descriptive extract to index.")
            chunks = []
            for i, row in enumerate(rows):
                text = f"Record {i + 1}: " + "; ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                chunks.append((text[:4000], text[:4000]))
        if len(chunks) > 4000:
            raise ValueError("Document exceeds 4,000 chunks. Split it into smaller files.")
        vectors = [None] * len(chunks)
        if strategy == "hybrid":
            vectors = embedding_model().encode([c[0] for c in chunks], normalize_embeddings=True).tolist()
        with store.connection() as db:
            # Recheck ownership inside the transaction; replace only after successful generation.
            if not db.execute("SELECT 1 FROM datasets WHERE id=? AND owner=?", (dataset_id, owner)).fetchone():
                raise ValueError("Dataset was removed during indexing.")
            db.execute("DELETE FROM chunks WHERE dataset=?", (dataset_id,))
            db.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)", [(dataset_id, i, text, parent, json.dumps(vectors[i]) if vectors[i] is not None else None) for i, (text, parent) in enumerate(chunks)])
            db.execute("UPDATE datasets SET status='ready',strategy=?,error='' WHERE id=? AND owner=?", (strategy, dataset_id, owner))
        store.audit(owner, "index_completed", dataset_id, {"strategy": strategy, "chunks": len(chunks)})
        return len(chunks)
    except Exception:
        with store.connection() as db:
            db.execute("UPDATE datasets SET status='failed',error=? WHERE id=? AND owner=?", ("Index build failed. Check local model availability or choose BM25.", dataset_id, owner))
        store.audit(owner, "index_failed", dataset_id, {"strategy": strategy})
        raise


def bm25_scores(query, texts):
    terms = tokens(query)
    corpus = [Counter(tokens(t)) for t in texts]
    n = len(corpus)
    if not n or not terms:
        return [0.0] * n
    lengths = [sum(c.values()) for c in corpus]
    average = sum(lengths) / n or 1
    frequencies = {term: sum(term in c for c in corpus) for term in set(terms)}
    scores = []
    for doc, length in zip(corpus, lengths):
        score = 0.0
        for term in set(terms):
            df = frequencies[term]
            idf = math.log(1 + (n - df + .5) / (df + .5))
            freq = doc[term]
            score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * length / average))
        scores.append(score)
    return scores


def search(owner, question, dataset_id=None, top_k=4):
    if not question.strip() or len(question) > 2000 or not 1 <= top_k <= 20:
        raise ValueError("Use a question of 1–2,000 characters and top_k from 1 to 20.")
    sql = """SELECT c.*,d.name,d.strategy FROM chunks c JOIN datasets d ON c.dataset=d.id
             WHERE d.owner=? AND d.status='ready'"""
    args = [owner]
    if dataset_id:
        sql += " AND d.id=?"
        args.append(dataset_id)
    with store.connection() as db:
        rows = [dict(r) for r in db.execute(sql, args)]
    if not rows:
        return []
    scores = bm25_scores(question, [r["text"] for r in rows])
    order = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
    fused = {idx: 1 / (60 + rank + 1) for rank, idx in enumerate(order)}
    dense_rows = [i for i, r in enumerate(rows) if r["vector"]]
    dense_scores = {}
    if dense_rows:
        vector = embedding_model().encode(question, normalize_embeddings=True).tolist()
        for i in dense_rows:
            stored = json.loads(rows[i]["vector"])
            dense_scores[i] = sum(a * b for a, b in zip(vector, stored))
        for rank, i in enumerate(sorted(dense_rows, key=lambda i: dense_scores[i], reverse=True)):
            fused[i] += 1 / (60 + rank + 1)
        order = sorted(fused, key=fused.get, reverse=True)
    # Deterministic lexical reranking is explicit, not represented as a neural reranker.
    query_terms = set(tokens(question))
    candidates = order[:20]
    candidates.sort(key=lambda i: (len(query_terms.intersection(tokens(rows[i]["text"]))) / max(1, len(query_terms)), fused[i]), reverse=True)
    hits = []
    for i in candidates:
        if scores[i] <= 0 and dense_scores.get(i, -1) < .35:
            continue
        r = rows[i]
        hits.append({"source": r["name"], "citation": f"{r['dataset']}:{r['ordinal']}",
                     "text": r["parent"] if r["strategy"] == "parent_child" else r["text"],
                     "score": round(scores[i], 4), "strategy": r["strategy"]})
        if len(hits) >= top_k:
            break
    return hits


def extractive_answer(hits):
    if not hits:
        return "I do not know based on the indexed documents. Upload and index relevant evidence first."
    return "\n\n".join(f"{hit['text']}\n\n[{i + 1}] {hit['source']} · {hit['citation']}" for i, hit in enumerate(hits))


def evaluate_retrieval(owner, dataset_id, question, expected_text):
    if not expected_text.strip():
        raise ValueError("Enter an expected evidence phrase.")
    started = time.perf_counter()
    hits = search(owner, question, dataset_id, top_k=5)
    rank = next((i + 1 for i, h in enumerate(hits) if expected_text.lower() in h["text"].lower()), None)
    return {"hit_at_5": int(rank is not None), "reciprocal_rank": 1 / rank if rank else 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1), "retrieved": len(hits)}
