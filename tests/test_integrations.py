import json

import pytest

from cortex import integrations


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def iter_content(self, size):
        yield json.dumps(self.payload).encode()

    def close(self):
        return None


def test_routemind_contract_and_data_projection(monkeypatch):
    monkeypatch.setenv("LOGISTICS_BASE_URL", "http://127.0.0.1:8000")
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"status": "completed", "summary": "Private customer at a private address", "routes": [{"vehicle_id": "SECRET", "stops": [{"name": "Private", "address": "Private Street"}], "total_distance_km": 12.5, "total_duration_minutes": 30, "traffic_delay_minutes": 2, "total_load_kg": 50, "estimated_cost": 10}]})
    monkeypatch.setattr(integrations.requests, "get", get)
    result = integrations.logistics_plan("run-123")
    assert calls[0][0].endswith("/api/plans/run-123")
    assert calls[0][1]["allow_redirects"] is False
    assert result["routes"][0]["total_distance_km"] == 12.5
    assert "Private" not in json.dumps(result) and "SECRET" not in json.dumps(result)
    with pytest.raises(ValueError):
        integrations.logistics_plan("../../admin")


def test_market_freshness_and_unconfigured(monkeypatch):
    monkeypatch.delenv("MARKET_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        integrations.market_snapshot()
    monkeypatch.setenv("MARKET_BASE_URL", "https://market.example")
    monkeypatch.setattr(integrations, "_get", lambda *args: {"as_of": "2020-01-01T00:00:00Z", "indicators": [{"name": "Index", "value": 1.2, "unit": "points"}]})
    assert integrations.market_snapshot()["stale"] is True


def test_remote_http_blocked():
    with pytest.raises(ValueError, match="HTTPS"):
        integrations._get("http://external.example", "/snapshot")


def test_cloud_request_contains_no_question_or_identifiers(tmp_path, monkeypatch):
    import pandas as pd
    from cortex import store
    from cortex.agents import run_agents
    monkeypatch.setenv("CORTEX_DB", str(tmp_path / "cloud.sqlite3"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    store.initialize()
    user = store.signup("private@example.test", "a-long-cloud-test-password")
    frame = pd.DataFrame([{"date": pd.Timestamp("2026-10-01"), "revenue": 10, "product": "Confidential Product", "customer_id": f"Private-{i % 5}"} for i in range(20)])
    recorded = []
    class CloudResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": "Aggregate explanation."}}]}
    def post(url, **kwargs):
        recorded.append(kwargs["json"])
        return CloudResponse()
    monkeypatch.setattr("requests.post", post)
    result = run_agents(user["id"], "Private Person at Private Street with bank DE123", "analytics", "Cloud aggregates", frame)
    serialized = json.dumps(recorded)
    for secret in ("Private", "Confidential", "DE123", "private@example.test"):
        assert secret not in serialized
    assert result["summary"]["revenue"] == 200


def test_xlsx_parser_and_empty_pdf():
    import io
    import pandas as pd
    from pypdf import PdfWriter
    from cortex.data import parse_file
    buffer = io.BytesIO()
    pd.DataFrame([{"date": "2026-10-01", "product": "A", "customer_id": "C-1", "revenue": 5}]).to_excel(buffer, index=False)
    kind, payload = parse_file("records.xlsx", buffer.getvalue())
    assert kind == "table" and payload["rows"][0]["revenue"] == 5
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    with pytest.raises(ValueError, match="No usable text"):
        parse_file("blank.pdf", pdf.getvalue())
