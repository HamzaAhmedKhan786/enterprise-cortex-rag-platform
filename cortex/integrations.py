"""Read-only server-configured connectors; raw upstream responses never enter AI."""
import os
import re
import math
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


def _get(base, path, key=""):
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Configure a valid server-side integration URL.")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "host.docker.internal", "routemind"}:
        raise ValueError("Remote integrations require HTTPS.")
    response = requests.get(base.rstrip("/") + path, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=(3, 10), allow_redirects=False, stream=True)
    try:
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError("Integration redirects are not allowed.")
        data = bytearray()
        for part in response.iter_content(65536):
            data.extend(part)
            if len(data) > 2_000_000:
                raise ValueError("Integration response exceeds 2 MB.")
        import json
        return json.loads(data)
    finally:
        response.close()


def logistics_health():
    base = os.getenv("LOGISTICS_BASE_URL", "")
    if not base:
        raise ValueError("Set LOGISTICS_BASE_URL to your RouteMind server.")
    data = _get(base, "/api/health", os.getenv("LOGISTICS_API_KEY", ""))
    return {k: data.get(k) for k in ("status", "orchestrator", "location_provider", "routing_provider")}


def logistics_plan(run_id):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", run_id):
        raise ValueError("Use a valid RouteMind plan/run ID.")
    base = os.getenv("LOGISTICS_BASE_URL", "")
    if not base:
        raise ValueError("Set LOGISTICS_BASE_URL before fetching a plan.")
    data = _get(base, f"/api/plans/{run_id}", os.getenv("LOGISTICS_API_KEY", ""))
    # RouteMind is a planning API, not a carrier tracking feed. Exclude stop names,
    # addresses, geometry, and arbitrary natural-language upstream output.
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        raise ValueError("Unexpected RouteMind routes response.")
    safe_routes = []
    for i, route in enumerate(routes[:500]):
        if not isinstance(route, dict):
            continue
        item = {"route_number": i + 1}
        for k in ("total_distance_km", "total_duration_minutes", "traffic_delay_minutes", "total_load_kg", "estimated_cost"):
            value = route.get(k)
            if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
                item[k] = value
        safe_routes.append(item)
    status = data.get("status")
    return {"plan_id": run_id, "status": status if status in {"success", "failed", "completed", "awaiting_approval", "needs_approval", "approved", "partial", "ok"} else "See RouteMind",
            "routes": safe_routes, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "notice": "Fetched from RouteMind now. Source traffic/location may be simulated. This is plan data, not live vehicle GPS or carrier shipment tracking."}


def market_snapshot():
    base = os.getenv("MARKET_BASE_URL", "")
    if not base:
        raise ValueError("Market connector is not configured. No market figures are fabricated.")
    # Contract: GET /snapshot -> {as_of: ISO8601, indicators: [{name,value,unit}]}.
    data = _get(base, "/snapshot", os.getenv("MARKET_API_KEY", ""))
    if not isinstance(data.get("indicators"), list) or not data.get("as_of"):
        raise ValueError("Market provider must return as_of and indicators.")
    timestamp = datetime.fromisoformat(data["as_of"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Market timestamp must include a timezone.")
    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    if age < -300:
        raise ValueError("Market timestamp is in the future.")
    rows = []
    for row in data["indicators"][:100]:
        if isinstance(row, dict) and isinstance(row.get("value"), (int, float)) and not isinstance(row["value"], bool) and math.isfinite(row["value"]):
            rows.append({"indicator": str(row.get("name", ""))[:80], "value": row["value"], "unit": str(row.get("unit", ""))[:20]})
    return {"as_of": timestamp.isoformat(), "stale": age > 86400, "indicators": rows}
