"""Deterministic authorization, upload inspection and local ClamAV transport."""
import io
import os
import re
import socket
import struct
import zipfile
from pathlib import Path

from cortex import store

ALLOWED = {".csv", ".json", ".txt", ".xlsx", ".pdf"}
MAX_UPLOAD = 100 * 1024 * 1024


def require_admin(owner):
    if not os.getenv("CORTEX_ADMIN_USER_ID") or owner != os.getenv("CORTEX_ADMIN_USER_ID"):
        raise ValueError("This action requires the operator-assigned administrator account.")


def static_inspect(name, raw):
    if not raw or len(raw) > MAX_UPLOAD:
        raise ValueError("Files must contain 1 byte–100 MiB before splitting.")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Only CSV, JSON, TXT, XLSX and PDF uploads are allowed.")
    if raw.startswith((b"MZ", b"\x7fELF")):
        raise ValueError("Executable content is blocked.")
    if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in raw:
        raise ValueError("Antivirus test signature detected; upload blocked.")
    if suffix == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise ValueError("File content does not match XLSX format.")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 5000 or sum(i.file_size for i in infos) > 50 * 1024 * 1024:
                raise ValueError("Workbook expansion exceeds the safety limit.")
            if "[Content_Types].xml" not in archive.namelist() or "xl/workbook.xml" not in archive.namelist():
                raise ValueError("Not a valid XLSX workbook.")
            for info in infos:
                lower = info.filename.lower()
                if any(token in lower for token in ("vbaproject", "activex", "externallinks", "embeddings/")):
                    raise ValueError("Macros, active objects and external workbook links are blocked.")
                if lower.endswith((".xml", ".rels")):
                    content = archive.read(info)
                    if re.search(rb"<(?:(?:\w+):)?f(?:\s|>)|TargetMode\s*=\s*[\"']External", content, re.I):
                        raise ValueError("Workbook formulas and external relationships are blocked. Upload a values-only export.")
    elif suffix == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("File content does not match PDF format.")
        # Check decoded PDF objects too: byte searches alone miss compressed scripts.
        from pypdf import PdfReader
        from pypdf.generic import IndirectObject, DictionaryObject, ArrayObject
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or len(reader.pages) > 200:
            raise ValueError("Encrypted PDFs or more than 200 pages are blocked.")
        stack, visited = [reader.trailer], set()
        forbidden = {"/JavaScript", "/JS", "/AA", "/OpenAction", "/Launch", "/EmbeddedFiles", "/RichMedia"}
        while stack:
            obj = stack.pop()
            if isinstance(obj, IndirectObject):
                key = (obj.idnum, obj.generation)
                if key in visited:
                    continue
                visited.add(key)
                if len(visited) > 50_000:
                    raise ValueError("PDF object graph exceeds the inspection limit.")
                obj = obj.get_object()
            if isinstance(obj, DictionaryObject):
                if forbidden.intersection(map(str, obj.keys())) or str(obj.get("/S", "")) in forbidden:
                    raise ValueError("PDF scripts, launch actions and embedded attachments are blocked.")
                stack.extend(obj.values())
            elif isinstance(obj, ArrayObject):
                stack.extend(obj)
    else:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("Binary content is not allowed in text uploads.")
        if re.search(r"<script\b|javascript\s*:|<\?php|^#!.*(?:bash|python|powershell)", text, re.I | re.M):
            raise ValueError("Script-like active content is blocked. Upload a plain data export.")
        if suffix == ".csv":
            import csv
            for row in csv.reader(io.StringIO(text)):
                if any(re.match(r"^\s*[=+@]", cell) or (cell.lstrip().startswith("-") and not re.fullmatch(r"\s*-\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*", cell)) for cell in row):
                    raise ValueError("Spreadsheet formula-like cells are blocked. Use a values-only CSV.")
    return {"static_checks": "passed", "bytes": len(raw), "format": suffix}


def clamav_scan(raw):
    host = os.getenv("CLAMAV_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1", "clamav", "host.docker.internal"}:
        raise ValueError("ClamAV must run on the approved local/internal network.")
    try:
        with socket.create_connection((host, int(os.getenv("CLAMAV_PORT", "3311"))), timeout=5) as client:
            client.settimeout(60)
            client.sendall(b"zINSTREAM\0")
            for start in range(0, len(raw), 65536):
                part = raw[start:start + 65536]
                client.sendall(struct.pack("!I", len(part)) + part)
            client.sendall(struct.pack("!I", 0))
            result = bytearray()
            while b"\0" not in result and b"\n" not in result:
                part = client.recv(4096)
                if not part:
                    break
                result.extend(part)
                if len(result) > 8192:
                    raise ValueError("Unexpected antivirus response.")
        reply = bytes(result).strip(b"\0\r\n")
        if reply != b"stream: OK":
            raise ValueError("Antivirus rejected the file or could not scan it completely.")
        return "no_known_malware_detected"
    except OSError:
        raise ValueError("Upload blocked: local ClamAV is unavailable. Start the scanner; files are never accepted as antivirus-clean without a scan.") from None


def scan_upload(owner, name, raw):
    store.audit(owner, "upload_scan_started", detail={"bytes": len(raw)})
    try:
        if not raw or len(raw) > MAX_UPLOAD or Path(name).suffix.lower() not in ALLOWED:
            raise ValueError("Unsupported or oversized upload.")
        antivirus = clamav_scan(raw)
        result = static_inspect(name, raw)
        result["antivirus"] = antivirus
        store.audit(owner, "upload_scan_passed", detail={"bytes": len(raw)})
        return result
    except Exception:
        store.audit(owner, "upload_scan_blocked", detail={"bytes": len(raw)})
        raise


def posture(owner):
    return [
        {"control": "Account isolation", "state": "Active", "detail": "Files, indexes and conversations are scoped by account ID."},
        {"control": "Cloud raw-content egress", "state": "Blocked by policy", "detail": "Names, addresses, bank details, raw text and prompts remain local."},
        {"control": "Aggregate cloud explanations", "state": "Enabled" if store.preferences(owner)["cloud_aggregates"] else "Disabled by workspace", "detail": "Numeric allowlist and minimum-cohort checks always apply."},
        {"control": "Upload gate", "state": "Fail closed", "detail": "Static inspection and a successful local ClamAV scan are required."},
        {"control": "Password protection", "state": "Active", "detail": "Salted PBKDF2, login lockout and eight-hour sessions."},
        {"control": "SSO / MFA", "state": "Not implemented", "detail": "Required before public enterprise deployment."},
    ]
