"""Administrator-only, bounded Snowflake migration; no arbitrary SQL or overwrite."""
import os
import re
import secrets
import time

import pandas as pd

from cortex import data, security, store


def identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value or ""):
        raise ValueError("Use a simple Snowflake identifier (letters, numbers and underscores).")
    return '"' + value.upper() + '"'


def connect():
    import snowflake.connector
    required = {k: os.getenv("SNOWFLAKE_" + k.upper(), "") for k in ("account", "user", "database", "schema", "warehouse", "role")}
    if not all(required.values()):
        raise ValueError("Configure Snowflake account, user, database, schema, warehouse and role on the server.")
    for field in ("database", "schema", "warehouse", "role"):
        identifier(required[field])
    credentials = {"private_key_file": os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]} if os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE") else {"password": os.getenv("SNOWFLAKE_PASSWORD", "")}
    if not any(credentials.values()):
        raise ValueError("Configure a Snowflake private key file or password.")
    return snowflake.connector.connect(**required, **credentials, login_timeout=15, network_timeout=30, session_parameters={"QUERY_TAG": "cortex-migration", "STATEMENT_TIMEOUT_IN_SECONDS": 60})


def _qualified(table):
    return ".".join(identifier(os.getenv("SNOWFLAKE_" + k, "")) for k in ("DATABASE", "SCHEMA")) + "." + identifier(table)


def check(owner):
    security.require_admin(owner)
    conn = connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ACCOUNT(),CURRENT_DATABASE(),CURRENT_SCHEMA()")
            row = cursor.fetchone()
        return {"account": row[0], "database": row[1], "schema": row[2]}
    finally:
        conn.close()


def export_dataset(owner, dataset_id, confirmed=False):
    security.require_admin(owner)
    if not confirmed:
        raise ValueError("Explicit confirmation is required before exporting customer data to Snowflake.")
    item = store.dataset(owner, dataset_id)
    if item["kind"] != "table":
        raise ValueError("Only structured table datasets can be exported.")
    # Content-addressed, tenant-prefixed destination; retries do not append rows.
    table = f"CORTEX_{owner.upper()}_{dataset_id.upper()}"
    target = _qualified(table)
    job = secrets.token_hex(12)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT * FROM migrations WHERE owner=? AND dataset=? AND direction='export' AND destination=?", (owner, dataset_id, target)).fetchone()
        if prior:
            if prior["status"] == "completed":
                return {"job": prior["id"], "table": table, "rows": prior["rows"], "status": "already_exported"}
            raise ValueError("An earlier export is pending or failed. Operator reconciliation is required; no automatic append/overwrite will occur.")
        db.execute("INSERT INTO migrations VALUES(?,?,?,?,?,?,?,?)", (job, owner, dataset_id, "export", target, "running", 0, time.time()))
    try:
        frame = pd.DataFrame(item["payload"]["rows"])
        frame.columns = [str(c).upper() for c in frame.columns]
        conn = connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM " + ".".join(identifier(os.getenv("SNOWFLAKE_" + k, "")) for k in ("DATABASE",)) + ".INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (os.environ["SNOWFLAKE_SCHEMA"].upper(), table))
                if cursor.fetchone()[0]:
                    raise ValueError("Destination already exists outside a completed migration. No rows were appended.")
            from snowflake.connector.pandas_tools import write_pandas
            success, _, rows, _ = write_pandas(conn, frame, table, database=os.environ["SNOWFLAKE_DATABASE"].upper(), schema=os.environ["SNOWFLAKE_SCHEMA"].upper(), auto_create_table=True, overwrite=False, quote_identifiers=True)
            if not success or rows != len(frame):
                raise ValueError("Snowflake row-count verification failed; reconcile the destination before retrying.")
        finally:
            conn.close()
        with store.connection() as db:
            db.execute("UPDATE migrations SET status='completed',rows=? WHERE id=? AND owner=?", (rows, job, owner))
        store.audit(owner, "snowflake_export_completed", job, {"rows": rows})
        return {"job": job, "table": table, "rows": rows, "status": "completed"}
    except Exception:
        with store.connection() as db:
            db.execute("UPDATE migrations SET status='failed' WHERE id=? AND owner=?", (job, owner))
        store.audit(owner, "snowflake_export_failed", job)
        raise


def import_table(owner, table, confirmed=False):
    security.require_admin(owner)
    if not confirmed:
        raise ValueError("Confirm importing this Snowflake table into local workspace storage.")
    identifier(table)
    table = table.upper()
    allowed = {t.strip().upper() for t in os.getenv("SNOWFLAKE_ALLOWED_TABLES", "").split(",") if t.strip()}
    with store.connection() as db:
        exports = db.execute("SELECT destination FROM migrations WHERE owner=? AND direction='export' AND status='completed'", (owner,)).fetchall()
    if table not in allowed and _qualified(table) not in {row[0] for row in exports}:
        raise ValueError("This table is not allowlisted or a completed export from this workspace.")
    conn = connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM " + _qualified(table) + " LIMIT 50001")
            if len(cursor.description) > 100:
                raise ValueError("Import is limited to 100 columns.")
            rows = cursor.fetchmany(50001)
            if len(rows) > data.MAX_ROWS:
                raise ValueError("Import exceeds 50,000 rows; narrow the source through an approved view.")
            columns = [col[0] for col in cursor.description]
    finally:
        conn.close()
    if not rows:
        raise ValueError("The source table is empty.")
    raw = pd.DataFrame(rows, columns=columns).to_csv(index=False).encode()
    if len(raw) > data.MAX_BYTES:
        raise ValueError("Import exceeds 10 MiB; use smaller approved source views.")
    dataset_id = data.ingest(owner, table + ".csv", raw)
    job = secrets.token_hex(12)
    with store.connection() as db:
        db.execute("INSERT INTO migrations VALUES(?,?,?,?,?,?,?,?)", (job, owner, dataset_id, "import", _qualified(table), "completed", len(rows), time.time()))
    store.audit(owner, "snowflake_import_completed", job, {"rows": len(rows)})
    return {"job": job, "dataset_id": dataset_id, "rows": len(rows)}
