"""Bounded ingestion, transparent profiling and deterministic business metrics."""
import hashlib
import io
import json
import random
import re
import secrets
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from cortex import store

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
METRIC_COLUMNS = {"date", "product", "customer_id", "category", "region", "quantity", "unit_price", "revenue", "cost", "status", "delivery_days", "promised_days"}
REQUIRED = {"date", "product", "customer_id", "revenue"}


def parse_file(name, raw, max_bytes=MAX_BYTES):
    if not raw or len(raw) > max_bytes:
        raise ValueError("File is empty or exceeds the permitted size.")
    suffix = Path(name).suffix.lower()
    if suffix == ".txt":
        text = raw.decode("utf-8-sig")
        payload = {"text": text}
        kind = "document"
    elif suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("Use an unencrypted PDF with at most 200 pages.")
        payload = {"text": "\n\n".join(p.extract_text() or "" for p in reader.pages)}
        kind = "document"
    elif suffix in {".csv", ".json", ".xlsx"}:
        if suffix == ".csv":
            frame = pd.read_csv(io.BytesIO(raw), nrows=MAX_ROWS + 1)
        elif suffix == ".xlsx":
            import zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError("Expanded workbook exceeds 50 MB.")
            frame = pd.read_excel(io.BytesIO(raw), nrows=MAX_ROWS + 1)
        else:
            value = json.loads(raw)
            if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
                raise ValueError("JSON must contain a flat array of row objects.")
            if any(isinstance(v, (dict, list)) for r in value for v in r.values()):
                raise ValueError("Flatten nested JSON fields before uploading.")
            frame = pd.DataFrame(value)
        if len(frame) > MAX_ROWS or len(frame.columns) > 100 or frame.empty:
            raise ValueError("Tables must contain 1–50,000 rows and at most 100 columns.")
        frame.columns = [str(c).strip().lower().replace(" ", "_") for c in frame.columns]
        if frame.columns.duplicated().any():
            raise ValueError("Column names must be unique after normalization.")
        payload = {"rows": json.loads(frame.to_json(orient="records", date_format="iso"))}
        kind = "table"
    else:
        raise ValueError("Supported formats: CSV, JSON, XLSX, PDF and UTF-8 TXT.")
    if kind == "document" and (not payload["text"].strip() or len(payload["text"]) > 10_000_000):
        raise ValueError("No usable text found, or text exceeds 10 million characters. Scanned PDFs need OCR first.")
    return kind, payload


def profile(kind, payload):
    if kind == "document":
        text = payload["text"]
        return {"characters": len(text), "words": len(text.split()), "paragraphs": len(text.split("\n\n")),
                "recommendation": "parent_child" if len(text) > 8000 else "bm25",
                "reason": "Long documents benefit from surrounding paragraph context." if len(text) > 8000 else "Use BM25 as a fast offline baseline; compare hybrid retrieval when local embedding models are ready.",
                "sample_method": "Evenly spaced sections; no data leaves this server."}
    frame = pd.DataFrame(payload["rows"])
    missing = int(frame.isna().sum().sum())
    duplicate = int(frame.duplicated().sum())
    return {"rows": len(frame), "columns": len(frame.columns), "column_names": list(frame.columns),
            "missing_cells": missing, "duplicate_rows": duplicate,
            "analytics_ready": REQUIRED.issubset(frame.columns),
            "recommendation": "sql_analytics", "reason": "Compute numbers deterministically from validated rows. Use document retrieval for descriptive content.",
            "sample_method": "Full bounded-table statistics, not an AI estimate."}


def ingest(owner, name, raw):
    kind, payload = parse_file(name, raw)
    digest = hashlib.sha256(raw).hexdigest()
    dataset_id = secrets.token_hex(16)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        from cortex.billing import limits
        cap = limits(owner, db)
        existing = db.execute("SELECT id FROM datasets WHERE owner=? AND digest=?", (owner, digest)).fetchone()
        if existing:
            return existing[0]
        usage = db.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(raw)),0) FROM datasets WHERE owner=?", (owner,)).fetchone()
        if usage[0] >= cap["files"] or usage[1] + len(raw) > cap["storage_mb"] * 1024 * 1024:
            raise ValueError("Workspace file or storage allowance reached. Review Billing usage or remove unused datasets.")
        db.execute("INSERT INTO datasets(id,owner,name,kind,digest,raw,payload,profile,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (dataset_id, owner, Path(name).name[:200], kind, digest, raw, json.dumps(payload), json.dumps(profile(kind, payload)), "uploaded", time.time()))
    store.audit(owner, "dataset_uploaded", dataset_id, {"bytes": len(raw), "kind": kind})
    return dataset_id


def representative_sample(text, max_chars=6000):
    if len(text) <= max_chars:
        return text
    size = max_chars // 3
    return "\n…\n".join(text[start:start + size] for start in (0, len(text) // 2 - size // 2, len(text) - size))


def validate_records(rows):
    frame = pd.DataFrame(rows)
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError("Analytics requires columns: " + ", ".join(sorted(missing)))
    if "currency" in frame and set(frame.currency.dropna().astype(str).str.upper()) - {"EUR"}:
        raise ValueError("This release requires EUR values. Convert other currencies before analytics.")
    frame = frame[[c for c in frame.columns if c in METRIC_COLUMNS]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True, format="mixed").dt.tz_convert(None)
    for col in ("revenue", "cost", "quantity", "unit_price", "delivery_days", "promised_days"):
        if col in frame:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
            frame[col] = frame[col].where(frame[col].abs() < 1e12)
    invalid = frame["date"].isna() | frame["revenue"].isna() | frame["product"].isna() | frame["customer_id"].isna()
    rejected = int(invalid.sum())
    frame = frame.loc[~invalid].copy()
    for col in ("product", "customer_id", "category", "region", "status"):
        if col in frame:
            frame[col] = frame[col].fillna("Unknown").astype(str)
    return frame, rejected


def filter_records(frame, start=None, end=None, products=None, customers=None):
    result = frame.copy()
    if start:
        result = result[result.date >= pd.Timestamp(start)]
    if end:
        result = result[result.date < pd.Timestamp(end) + pd.Timedelta(days=1)]
    if products:
        result = result[result["product"].isin(products)]
    if customers:
        result = result[result["customer_id"].isin(customers)]
    return result


def metrics(frame):
    if frame.empty:
        return {"records": 0, "revenue": 0.0, "customers": 0, "products": 0, "average_record_value": 0.0}
    result = {"records": len(frame), "revenue": round(float(frame.revenue.sum()), 2),
              "customers": int(frame.customer_id.nunique()), "products": int(frame["product"].nunique()),
              "average_record_value": round(float(frame.revenue.mean()), 2)}
    if "cost" in frame:
        complete = frame.cost.notna().all()
        if complete:
            result["margin_pct"] = round(float((frame.revenue.sum() - frame.cost.sum()) / frame.revenue.sum() * 100), 2) if frame.revenue.sum() else 0.0
    if {"delivery_days", "promised_days"}.issubset(frame.columns):
        valid = frame.dropna(subset=["delivery_days", "promised_days"])
        if not valid.empty:
            result["on_time_pct"] = round(float((valid.delivery_days <= valid.promised_days).mean() * 100), 2)
    return result


def strategies(frame):
    m = metrics(frame)
    if not m["records"]:
        return [{"priority": "Info", "signal": "No matching records", "action": "Widen the date or product filters.", "evidence": "0 records", "rule": "empty_selection"}]
    actions = []
    if m.get("on_time_pct", 100) < 95:
        actions.append({"priority": "High", "signal": "Delivery SLA below target", "action": "Review delayed routes and carrier capacity; validate RouteMind provider freshness before dispatch changes.", "evidence": f"{m['on_time_pct']}% on time; target 95%", "rule": "on_time_pct < 95"})
    if m.get("margin_pct", 100) < 20:
        actions.append({"priority": "High", "signal": "Margin pressure", "action": "Inspect unit economics and discount policies before changing prices.", "evidence": f"{m['margin_pct']}% contribution margin; threshold 20%", "rule": "margin_pct < 20"})
    top = frame.groupby("customer_id").revenue.sum().max()
    share = top / m["revenue"] * 100 if m["revenue"] > 0 else 0
    if share > 25:
        actions.append({"priority": "Medium", "signal": "Customer concentration", "action": "Review renewal exposure and diversify pipeline.", "evidence": f"Largest customer represents {share:.1f}% of selected revenue", "rule": "top_customer_share > 25"})
    actions.append({"priority": "Info", "signal": "Reconcile before acting", "action": "Compare the filtered report with accounting and returns; revenue is the sum of uploaded record values, not audited net revenue.", "evidence": f"{m['records']} records included", "rule": "always"})
    return actions


def safe_csv(frame):
    result = frame.copy()
    for col in result.select_dtypes(include=["object", "string"]).columns:
        result[col] = result[col].map(lambda v: "'" + v if isinstance(v, str) and re.match(r"^[\s]*[=+@\-]", v) else v)
    return result.to_csv(index=False).encode("utf-8-sig")


def seed_demo(owner):
    rng = random.Random(42)
    rows = []
    products = [("Studio Laptop", "Computing", 1249), ("Air Headphones", "Audio", 189), ("Focus Monitor", "Displays", 329), ("Travel Tablet", "Computing", 549), ("Mechanical Keyboard", "Accessories", 119)]
    for i in range(540):
        product, category, price = products[rng.randrange(len(products))]
        qty = rng.randint(1, 4)
        revenue = round(price * qty * rng.uniform(.9, 1.05), 2)
        rows.append({"date": str(date.today() - timedelta(days=rng.randrange(180))), "product": product, "category": category,
                     "customer_id": f"C-{rng.randrange(1, 61):03}", "region": rng.choice(["Berlin", "Hamburg", "Munich", "Cologne"]),
                     "quantity": qty, "revenue": revenue, "cost": round(revenue * rng.uniform(.62, .94), 2),
                     "status": rng.choice(["Delivered", "Delivered", "In transit", "Processing"]), "delivery_days": rng.randint(1, 7), "promised_days": 5})
    ingest(owner, "demo-commerce.csv", pd.DataFrame(rows).to_csv(index=False).encode())
    ingest(owner, "demo-policies.txt", b"Refund policy\nRefunds are processed within 5 business days after the returned item is received and inspected.\n\nShipping policy\nStandard shipping takes 3 to 5 business days. Expedited shipping takes 1 to 2 business days.\n\nDamaged items\nContact support with your order reference within 48 hours. Damaged products are eligible for return after verification.")
