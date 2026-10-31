"""Scan before split; record-aware table parts and exact binary reassembly manifests."""
import csv
import hashlib
import io
import json
import secrets
import time
import zipfile
import re
from pathlib import Path

from cortex import data, security, store

SPLIT_THRESHOLD = 10 * 1024 * 1024
PART_SIZE = 9 * 1024 * 1024


def safe_name(name):
    value = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"[^A-Za-z0-9._-]", "_", value)[:180]
    if value in {"", ".", ".."}:
        raise ValueError("Invalid upload filename.")
    return value


def split_file(name, raw):
    name = safe_name(name)
    suffix = Path(name).suffix.lower()
    stem = Path(name).stem[:120]
    if len(raw) < SPLIT_THRESHOLD:
        return [(Path(name).name, raw)], "original"
    if suffix in {".pdf", ".xlsx"}:
        return [(f"{stem}.1.{i + 1}{suffix}.part", raw[n:n + PART_SIZE]) for i, n in enumerate(range(0, len(raw), PART_SIZE))], "binary_exact"
    if suffix == ".txt":
        parts, start = [], 0
        while start < len(raw):
            end = min(start + PART_SIZE, len(raw))
            if end < len(raw):
                while end > start and raw[end] & 0xC0 == 0x80:
                    end -= 1
            parts.append((f"{stem}.1.{len(parts) + 1}.txt", raw[start:end]))
            start = end
        return parts, "utf8_exact"
    if suffix == ".csv":
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("CSV has no header.") from None
        def encode(row):
            buffer = io.StringIO(newline="")
            csv.writer(buffer).writerow(row)
            return buffer.getvalue().encode("utf-8")
        head = encode(header)
        if len(head) >= PART_SIZE:
            raise ValueError("CSV header exceeds a part's size limit.")
        parts, current, count = [], bytearray(head), 0
        for row in reader:
            encoded = encode(row)
            if len(head) + len(encoded) > PART_SIZE:
                raise ValueError("A CSV record exceeds 9 MiB and cannot be split safely.")
            if len(current) + len(encoded) > PART_SIZE or count >= data.MAX_ROWS:
                parts.append((f"{stem}.1.{len(parts) + 1}.csv", bytes(current)))
                current, count = bytearray(head), 0
            current.extend(encoded)
            count += 1
        if count:
            parts.append((f"{stem}.1.{len(parts) + 1}.csv", bytes(current)))
        return parts, "csv_records_with_headers"
    if suffix == ".json":
        rows = json.loads(raw)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("JSON must be a flat array of row objects.")
        parts, current, size = [], [], 2
        for row in rows:
            encoded = json.dumps(row, ensure_ascii=False).encode("utf-8")
            if len(encoded) + 2 > PART_SIZE:
                raise ValueError("A JSON record exceeds 9 MiB.")
            if current and (size + len(encoded) + 1 > PART_SIZE or len(current) >= data.MAX_ROWS):
                parts.append((f"{stem}.1.{len(parts) + 1}.json", b"[" + b",".join(current) + b"]"))
                current, size = [], 2
            current.append(encoded)
            size += len(encoded) + 1
        if current:
            parts.append((f"{stem}.1.{len(parts) + 1}.json", b"[" + b",".join(current) + b"]"))
        return parts, "json_records"
    raise ValueError("Unsupported split format.")


def secure_ingest(owner, name, raw):
    name = safe_name(name)
    scan = security.scan_upload(owner, name, raw)
    parts, method = split_file(name, raw)
    # PDF/XLSX fragments are byte containers, not valid standalone documents.
    sources = [(Path(name).name, raw)] if method == "binary_exact" else parts
    parsed = [(n, content, *data.parse_file(n, content, max_bytes=security.MAX_UPLOAD)) for n, content in sources]
    ids = []
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        pending, seen = [], {}
        for filename, content, kind, payload in parsed:
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                ids.append(seen[digest])
                continue
            existing = db.execute("SELECT id FROM datasets WHERE owner=? AND digest=?", (owner, digest)).fetchone()
            if existing:
                ids.append(existing[0])
                seen[digest] = existing[0]
            else:
                did = secrets.token_hex(16)
                pending.append((did, owner, filename, kind, digest, content, json.dumps(payload), json.dumps(data.profile(kind, payload)), "uploaded", time.time()))
                ids.append(did)
                seen[digest] = did
        usage = db.execute("SELECT COUNT(*),COALESCE(SUM(LENGTH(raw)),0) FROM datasets WHERE owner=?", (owner,)).fetchone()
        from cortex.billing import limits
        cap = limits(owner, db)
        if usage[0] + len(pending) > cap["files"] or usage[1] + sum(len(r[5]) for r in pending) > cap["storage_mb"] * 1024 * 1024:
            raise ValueError("Upload would exceed the workspace file or storage allowance. No parts were registered.")
        db.executemany("INSERT INTO datasets(id,owner,name,kind,digest,raw,payload,profile,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)", pending)
    manifest = {"version": 1, "method": method, "original_sha256": hashlib.sha256(raw).hexdigest(), "original_bytes": len(raw),
                "parts": [{"name": n, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()} for n, content in parts]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for filename, content in parts:
            archive.writestr(filename, content)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    store.audit(owner, "secure_upload_registered", detail={"datasets": len(ids), "parts": len(parts), "bytes": len(raw), "split": method})
    return {"dataset_ids": ids, "scan": scan, "manifest": manifest, "archive": buffer.getvalue()}
