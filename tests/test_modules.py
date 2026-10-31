import hashlib
import hmac
import io
import json
import time
import types
import zipfile

import pytest

from cortex import billing, data, logistics, security, store, uploads, warehouse


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_DB", str(tmp_path / "modules.sqlite3"))
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    store.initialize()
    return store.signup("module@example.test", "a-strong-module-password")["id"]


def test_password_change_revokes_old_sessions(owner):
    session = store.login("module@example.test", "a-strong-module-password")
    assert store.session_valid(session)
    store.change_password(owner, "a-strong-module-password", "a-new-strong-password")
    assert not store.session_valid(session)
    assert store.session_valid(store.login("module@example.test", "a-new-strong-password"))
    with pytest.raises(ValueError):
        store.login("module@example.test", "a-strong-module-password")


def test_static_scan_blocks_executables_scripts_and_spreadsheet_formulas():
    for name, raw in [("safe.txt", b"MZbinary"), ("bad.txt", b"<script>alert(1)</script>"), ("data.csv", b"x\n=HYPERLINK(1)"), ("test.txt", b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE")]:
        with pytest.raises(ValueError):
            security.static_inspect(name, raw)
    assert security.static_inspect("good.txt", b"A refund policy.")["static_checks"] == "passed"


def test_xlsx_external_and_formula_content_blocked():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet><f>HYPERLINK(1)</f></worksheet>")
    with pytest.raises(ValueError, match="formulas"):
        security.static_inspect("records.xlsx", buffer.getvalue())


def test_exact_threshold_and_utf8_split():
    raw = ("€" * ((uploads.SPLIT_THRESHOLD // 3) + 1)).encode()
    parts, method = uploads.split_file("file.txt", raw)
    assert method == "utf8_exact" and len(parts) == 2
    assert parts[0][0] == "file.1.1.txt" and parts[1][0] == "file.1.2.txt"
    assert all(len(content) <= uploads.PART_SIZE for _, content in parts)
    assert b"".join(content for _, content in parts) == raw
    assert all(content.decode("utf-8") for _, content in parts)
    assert len(uploads.split_file("file.txt", b"a" * (uploads.SPLIT_THRESHOLD - 1))[0]) == 1
    assert len(uploads.split_file("file.txt", b"a" * uploads.SPLIT_THRESHOLD)[0]) == 2
    assert uploads.split_file("../../unsafe.txt", b"safe")[0][0][0] == "unsafe.txt"
    assert uploads.split_file("..\\..\\unsafe.txt", b"safe")[0][0][0] == "unsafe.txt"


def test_csv_split_keeps_headers_and_quoted_records(monkeypatch):
    import csv
    monkeypatch.setattr(uploads, "SPLIT_THRESHOLD", 70)
    monkeypatch.setattr(uploads, "PART_SIZE", 60)
    raw = ('id,description\n1,"a multiline\nrecord with text"\n2,"second multiline\nrecord text"\n').encode()
    parts, method = uploads.split_file("file.csv", raw)
    assert method == "csv_records_with_headers"
    assert len(parts) == 2 and all(len(part) <= 60 for _, part in parts)
    combined = [row for _, content in parts for row in list(csv.reader(io.StringIO(content.decode())))[1:]]
    assert combined == list(csv.reader(io.StringIO(raw.decode())))[1:]


def test_clamav_missing_fails_closed_without_registering(owner, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr(security.socket, "create_connection", unavailable)
    with pytest.raises(ValueError, match="Upload blocked"):
        uploads.secure_ingest(owner, "good.txt", b"Policy content")
    assert store.datasets(owner) == []
    assert store.history(owner, "events")[0]["action"] == "upload_scan_blocked"


def test_secure_upload_manifest_and_atomic_invalid_data(owner, monkeypatch):
    monkeypatch.setattr(security, "clamav_scan", lambda raw: "no_known_malware_detected")
    result = uploads.secure_ingest(owner, "good.txt", b"Policy content")
    assert result["manifest"]["original_sha256"] == hashlib.sha256(b"Policy content").hexdigest()
    with zipfile.ZipFile(io.BytesIO(result["archive"])) as archive:
        assert archive.read("good.txt") == b"Policy content"
    before = len(store.datasets(owner))
    with pytest.raises((ValueError, json.JSONDecodeError)):
        uploads.secure_ingest(owner, "bad.json", b"invalid json")
    assert len(store.datasets(owner)) == before


def test_billing_blocks_live_mode_and_unknown_prices(owner, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_test_not_real")
    monkeypatch.delenv("STRIPE_ALLOW_LIVE", raising=False)
    with pytest.raises(ValueError, match="test secret"):
        billing.checkout(owner, "starter")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_real")
    monkeypatch.delenv("STRIPE_PRICE_STARTER", raising=False)
    with pytest.raises(ValueError, match="price ID"):
        billing.checkout(owner, "starter")


def test_checkout_customer_binding_and_subscription_refresh(owner, monkeypatch):
    import stripe
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_real")
    monkeypatch.setenv("STRIPE_PRICE_STARTER", "price_example")
    monkeypatch.setattr(stripe.Customer, "create", lambda **kwargs: {"id": "cus_example"})
    captured = []
    def session(**kwargs):
        captured.append(kwargs)
        return {"url": "https://checkout.stripe.com/test"}
    monkeypatch.setattr(stripe.checkout.Session, "create", session)
    assert billing.checkout(owner, "starter")["test_mode"] is True
    assert captured[0]["customer"] == "cus_example" and captured[0]["mode"] == "subscription"
    assert "card" not in json.dumps(captured)
    monkeypatch.setattr(stripe.Subscription, "list", lambda **kwargs: {"has_more": False, "data": [{"id": "sub_example", "status": "active", "created": 10, "items": {"data": [{"price": {"id": "price_example"}}]}}]})
    assert billing.refresh(owner)["plan"] == "starter"
    with pytest.raises(ValueError, match="existing subscription"):
        billing.checkout(owner, "starter")


def test_signed_webhook_replay_and_invalid_signature(owner, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_not_real")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_not_real")
    with store.connection() as db:
        db.execute("INSERT INTO billing_accounts(owner,customer,updated) VALUES(?,?,?)", (owner, "cus_local", time.time()))
    monkeypatch.setattr(billing, "_current_subscription", lambda customer: {"subscription": "sub_local", "plan": "starter", "status": "active"})
    event = {"id": "evt_example", "type": "customer.subscription.updated", "livemode": False, "data": {"object": {"customer": "cus_local"}}}
    raw = json.dumps(event).encode()
    timestamp = int(time.time())
    digest = hmac.new(b"whsec_test_not_real", str(timestamp).encode() + b"." + raw, hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={digest}"
    with pytest.raises(ValueError, match="signature"):
        billing.webhook(raw, f"t={timestamp},v1=wrong")
    assert billing.account(owner)["status"] == "unpaid"
    assert billing.webhook(raw, header)["status"] == "processed"
    assert billing.webhook(raw, header)["status"] == "duplicate"
    assert billing.account(owner)["plan"] == "starter"


def test_warehouse_authorization_identifiers_and_confirmation(owner, monkeypatch):
    with pytest.raises(ValueError, match="administrator"):
        warehouse.import_table(owner, "TABLE", True)
    monkeypatch.setenv("CORTEX_ADMIN_USER_ID", owner)
    with pytest.raises(ValueError, match="confirmation"):
        warehouse.export_dataset(owner, "missing")
    with pytest.raises(ValueError):
        warehouse.identifier('ORDERS; DROP TABLE USERS')
    assert warehouse.identifier("orders") == '"ORDERS"'
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "DB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "SCHEMA")
    with pytest.raises(ValueError, match="allowlisted"):
        warehouse.import_table(owner, "SECRET", True)


def test_warehouse_import_mocked_contract(owner, monkeypatch):
    monkeypatch.setenv("CORTEX_ADMIN_USER_ID", owner)
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "DB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    monkeypatch.setenv("SNOWFLAKE_ALLOWED_TABLES", "ORDERS")
    class Cursor:
        description = [("DATE",), ("PRODUCT",), ("CUSTOMER_ID",), ("REVENUE",)]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query): assert query == 'SELECT * FROM "DB"."PUBLIC"."ORDERS" LIMIT 50001'
        def fetchmany(self, limit): return [("2026-10-01", "A", "C-1", 20)]
    class Connection:
        def cursor(self): return Cursor()
        def close(self): pass
    monkeypatch.setattr(warehouse, "connect", lambda: Connection())
    result = warehouse.import_table(owner, "orders", True)
    assert result["rows"] == 1 and store.dataset(owner, result["dataset_id"])["kind"] == "table"


def test_logistics_plan_assignment_prevents_cross_workspace_fetch(owner, monkeypatch):
    other = store.signup("other-module@example.test", "another-strong-password")["id"]
    monkeypatch.setenv("CORTEX_ADMIN_USER_ID", owner)
    logistics.assign(owner, owner, "plan-123")
    monkeypatch.setattr(logistics.integrations, "logistics_plan", lambda pid: {"routes": [], "notice": "Synthetic test response"})
    assert logistics.fetch(owner, "plan-123")["routes"] == []
    with pytest.raises(ValueError, match="not assigned"):
        logistics.fetch(other, "plan-123")
    assert logistics.links(other) == []


def test_module_agents_carol_and_actual_deepeval(owner):
    from cortex.module_agents import CarolAgent, ObservabilityAgent, SecurityAgent
    result = CarolAgent().run(owner, "ask", question="What data goes to cloud AI?")
    assert "Only explicitly enabled numeric" in result["answer"]
    assert store.history(owner, "messages")[0]["answer"] == result["answer"]
    SecurityAgent().run(owner, "preferences", cloud_aggregates=True)
    assert store.preferences(owner)["cloud_aggregates"] is True
    evaluation = ObservabilityAgent().run(owner, "evaluate")
    assert evaluation["passed"] is True and evaluation["score"] == 1
    with pytest.raises(ValueError, match="unsupported"):
        SecurityAgent().run(owner, "execute_shell", command="anything")


def test_stripe_webhook_api_rejects_unsigned_payload(owner, monkeypatch):
    from fastapi.testclient import TestClient
    from cortex.api import app
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_not_real")
    with TestClient(app) as client:
        assert client.post("/webhooks/stripe", content=b'{}').status_code == 400
        assert client.post("/webhooks/stripe", content=b'x' * (256 * 1024 + 1)).status_code == 413


def test_warehouse_export_is_verified_and_retry_does_not_append(owner, monkeypatch):
    from snowflake.connector import pandas_tools
    monkeypatch.setenv("CORTEX_ADMIN_USER_ID", owner)
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "DB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    did = data.ingest(owner, "table.csv", b"date,product,customer_id,revenue\n2026-10-01,A,C-1,50\n")
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query, parameters):
            assert "INFORMATION_SCHEMA.TABLES" in query
            assert parameters[0] == "PUBLIC"
        def fetchone(self): return (0,)
    class Connection:
        def cursor(self): return Cursor()
        def close(self): pass
    monkeypatch.setattr(warehouse, "connect", lambda: Connection())
    written = []
    def write(conn, frame, table, **kwargs):
        written.append(table)
        assert kwargs["overwrite"] is False
        return True, 1, len(frame), []
    monkeypatch.setattr(pandas_tools, "write_pandas", write)
    assert warehouse.export_dataset(owner, did, True)["rows"] == 1
    assert warehouse.export_dataset(owner, did, True)["status"] == "already_exported"
    assert len(written) == 1
