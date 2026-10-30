"""Fail-closed egress policy: external AI sees numeric aggregates only."""
import math
import os
from urllib.parse import urlparse

AGGREGATES = {"records", "revenue", "customers", "products", "average_record_value", "margin_pct", "on_time_pct"}


def cloud_payload(metrics):
    result = {}
    for key, value in metrics.items():
        if key not in AGGREGATES or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Cloud AI accepts approved finite aggregate numbers only.")
        result[key] = value
    # Small groups remain local to reduce reidentification risk.
    if result.get("records", 0) < 10 or result.get("customers", 0) < 5:
        raise ValueError("Cloud analysis requires at least 10 records and 5 distinct customers.")
    return {"metrics": result, "task": "Explain these aggregate metrics. State limitations; do not invent causes or identifiers."}


def local_model_url():
    url = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"} or parsed.username or parsed.password:
        raise ValueError("Local models must use the approved loopback or internal Ollama service.")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid local model URL.")
    return url
