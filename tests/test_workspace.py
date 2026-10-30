import json
from datetime import date

import pandas as pd
import pytest

from cortex import data, store
from cortex.privacy import cloud_payload, local_model_url
from cortex.retrieval import build_index, evaluate_retrieval, search


@pytest.fixture
def users(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_DB", str(tmp_path / "workspace.sqlite3"))
    store.initialize()
    return store.signup("one@example.test", "a-strong-test-password"), store.signup("two@example.test", "another-strong-password")


def test_password_hash_and_login_lockout(users):
    user, _ = users
    assert store.login(user["email"], "a-strong-test-password")["id"] == user["id"]
    with store.connection() as db:
        record = dict(db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
    assert record["password_hash"] != "a-strong-test-password"
    for _ in range(5):
        with pytest.raises(ValueError, match="Invalid"):
            store.login(user["email"], "incorrect-password")
    with pytest.raises(ValueError, match="Too many"):
        store.login(user["email"], "a-strong-test-password")


def test_tenant_isolation_and_cascading_delete(users):
    a, b = users
    did = data.ingest(a["id"], "policy.txt", b"Refunds take 5 business days after inspection.")
    build_index(a["id"], did, "bm25")
    assert search(a["id"], "refunds")
    assert not search(b["id"], "refunds", did)
    assert store.datasets(b["id"]) == []
    with pytest.raises(ValueError):
        store.dataset(b["id"], did)
    store.delete_dataset(b["id"], did)
    assert store.dataset(a["id"], did)
    store.delete_dataset(a["id"], did)
    assert not search(a["id"], "refunds")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_duplicate_ingestion_and_parent_context(users):
    a, _ = users
    raw = b"Refund policy\nRefunds take five days.\n\nShipping takes two days."
    did = data.ingest(a["id"], "policy.txt", raw)
    assert data.ingest(a["id"], "renamed.txt", raw) == did
    build_index(a["id"], did, "parent_child")
    result = evaluate_retrieval(a["id"], did, "refund policy", "five days")
    assert result["hit_at_5"] == 1 and result["reciprocal_rank"] == 1
    assert search(a["id"], "unrelatedxyz") == []


def test_failed_reindex_is_recorded(users, monkeypatch):
    a, _ = users
    did = data.ingest(a["id"], "policy.txt", b"A refund takes five days.")
    def failed_model():
        raise RuntimeError("model unavailable")
    monkeypatch.setattr("cortex.retrieval.embedding_model", failed_model)
    with pytest.raises(RuntimeError):
        build_index(a["id"], did, "hybrid")
    assert store.dataset(a["id"], did)["status"] == "failed"
    assert store.history(a["id"], "events")[0]["action"] == "index_failed"


def test_inclusive_filters_and_invalid_records():
    rows = [{"date": "2026-10-01T22:00:00Z", "product": "A", "customer_id": "C1", "revenue": 100},
            {"date": "2026-10-02", "product": "B", "customer_id": "C2", "revenue": 200},
            {"date": "invalid", "product": "A", "customer_id": "C3", "revenue": 999}]
    frame, rejected = data.validate_records(rows)
    selected = data.filter_records(frame, date(2026, 10, 1), date(2026, 10, 1), ["A"], ["C1"])
    assert rejected == 1
    assert data.metrics(selected)["revenue"] == 100
    assert data.metrics(selected)["records"] == 1


def test_cloud_egress_is_fail_closed():
    values = {"records": 20, "customers": 5, "revenue": 500.0}
    assert cloud_payload(values)["metrics"] == values
    for extra in ({"customer_name": "Private Name"}, {"revenue": "123"}, {"revenue": float("nan")}, {"bank_details": 123}):
        with pytest.raises(ValueError):
            cloud_payload(values | extra)
    with pytest.raises(ValueError):
        cloud_payload(values | {"customers": 1})


def test_remote_local_model_blocked(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://external.example")
    with pytest.raises(ValueError):
        local_model_url()


def test_ingestion_bounds_and_formula_safe_export(users):
    a, _ = users
    for name, raw in [("bad.exe", b"bad"), ("empty.csv", b""), ("nested.json", b'[{"field":{"private":"value"}}]')]:
        with pytest.raises(ValueError):
            data.ingest(a["id"], name, raw)
    assert "'=SUM" in data.safe_csv(pd.DataFrame({"product": ["=SUM(A1)"]})).decode("utf-8-sig")


def test_graph_routes_and_persistence(users):
    from cortex.agents import run_agents
    a, b = users
    did = data.ingest(a["id"], "policy.txt", b"Refunds take five business days.")
    build_index(a["id"], did, "bm25")
    result = run_agents(a["id"], "refunds", "documents")
    assert "[1]" in result["answer"]
    assert len(result["steps"]) == 4
    assert len(store.history(a["id"], "runs")) == 1
    assert not store.history(b["id"], "messages")
    with pytest.raises(ValueError):
        run_agents(a["id"], "refunds", "documents", "Cloud aggregates")
    assert store.history(a["id"], "runs")[0]["status"] == "failed"
    store.erase_workspace(a["id"])
    assert not store.datasets(a["id"]) and not store.history(a["id"], "messages")


def test_same_table_can_power_analytics_and_retrieval(users):
    a, _ = users
    raw = b"date,product,customer_id,revenue,description\n2026-10-01,Keyboard,C-1,99,Mechanical keyboard with quiet keys\n"
    did = data.ingest(a["id"], "catalog.csv", raw)
    build_index(a["id"], did, "bm25")
    assert "quiet keys" in search(a["id"], "quiet keyboard", did)[0]["text"]
    frame, _ = data.validate_records(store.dataset(a["id"], did)["payload"]["rows"])
    assert data.metrics(frame)["revenue"] == 99


def test_analytics_rejects_mixed_currency():
    with pytest.raises(ValueError, match="EUR"):
        data.validate_records([{"date": "2026-10-01", "product": "A", "customer_id": "C", "revenue": 3, "currency": "USD"}])


def test_local_timeout_falls_back_to_evidence_and_metadata_metrics(users, monkeypatch):
    import httpx
    from cortex.agents import run_agents
    from cortex.metrics_server import render
    a, _ = users
    did = data.ingest(a["id"], "policy.txt", b"Refunds take five business days.")
    build_index(a["id"], did, "bm25")
    class UnavailableModel:
        def __init__(self, **kwargs):
            pass
        def invoke(self, messages):
            raise httpx.ReadTimeout("unavailable")
    monkeypatch.setattr("langchain_ollama.ChatOllama", UnavailableModel)
    result = run_agents(a["id"], "refunds", mode="Local Ollama")
    assert result["degraded"] is True
    assert "five business days" in result["answer"]
    assert store.history(a["id"], "runs")[0]["status"] == "degraded"
    metric_text = render()
    assert 'status="degraded"' in metric_text
    assert a["email"] not in metric_text and a["id"] not in metric_text
