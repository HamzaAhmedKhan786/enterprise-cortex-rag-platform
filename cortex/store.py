"""Local single-node persistence. All domain reads require a workspace owner."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def db_path():
    return Path(os.getenv("CORTEX_DB", "data/private/cortex.sqlite3"))


@contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL,
          password_hash TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (email TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS attempts_lookup ON attempts(email,created);
        CREATE TABLE IF NOT EXISTS datasets (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, kind TEXT NOT NULL, digest TEXT NOT NULL,
          raw BLOB NOT NULL, payload TEXT NOT NULL, profile TEXT NOT NULL,
          strategy TEXT NOT NULL DEFAULT 'bm25', status TEXT NOT NULL,
          error TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
          UNIQUE(owner,digest));
        CREATE TABLE IF NOT EXISTS chunks (
          dataset TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
          ordinal INTEGER NOT NULL, text TEXT NOT NULL, parent TEXT NOT NULL,
          vector TEXT, PRIMARY KEY(dataset,ordinal));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
          action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL,
          created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
          route TEXT NOT NULL, status TEXT NOT NULL, duration REAL NOT NULL,
          steps TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
          question TEXT NOT NULL, answer TEXT NOT NULL, sources TEXT NOT NULL,
          run_id TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback (
          owner TEXT NOT NULL REFERENCES users(id), run_id TEXT NOT NULL,
          rating TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(owner,run_id));
        CREATE TABLE IF NOT EXISTS preferences (
          owner TEXT PRIMARY KEY REFERENCES users(id), cloud_aggregates INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS billing_accounts (
          owner TEXT PRIMARY KEY REFERENCES users(id), customer TEXT UNIQUE NOT NULL,
          subscription TEXT NOT NULL DEFAULT '', plan TEXT NOT NULL DEFAULT 'free',
          status TEXT NOT NULL DEFAULT 'unpaid', updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS billing_events (id TEXT PRIMARY KEY, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS migrations (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), dataset TEXT NOT NULL,
          direction TEXT NOT NULL, destination TEXT NOT NULL, status TEXT NOT NULL,
          rows INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS logistics_links (
          owner TEXT NOT NULL REFERENCES users(id), plan_id TEXT NOT NULL,
          snapshot TEXT NOT NULL DEFAULT '{}', fetched REAL NOT NULL DEFAULT 0,
          PRIMARY KEY(owner,plan_id));
        """)
        db.execute("BEGIN IMMEDIATE")
        if "password_changed" not in {row[1] for row in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN password_changed REAL NOT NULL DEFAULT 0")
    from cortex.billing_schema import migrate
    migrate()


def _email(value):
    email = value.strip().lower()
    if not re.fullmatch(r"[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}", email):
        raise ValueError("Enter a valid email address.")
    return email


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


def signup(email, password):
    email = _email(email)
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a password with 12–256 characters.")
    uid, salt = secrets.token_hex(16), secrets.token_hex(16)
    try:
        with connection() as db:
            db.execute("INSERT INTO users(id,email,salt,password_hash,created) VALUES (?,?,?,?,?)", (uid, email, salt, _hash(password, salt), time.time()))
    except sqlite3.IntegrityError:
        raise ValueError("Unable to create account. Try signing in or use another address.") from None
    return {"id": uid, "email": email, "issued": time.time()}


def login(email, password):
    email = _email(email)
    if len(password) > 256:
        raise ValueError("Invalid email or password.")
    now = time.time()
    with connection() as db:
        db.execute("DELETE FROM attempts WHERE created < ?", (now - 900,))
        if db.execute("SELECT COUNT(*) FROM attempts WHERE email=?", (email,)).fetchone()[0] >= 5:
            raise ValueError("Too many attempts. Try again in 15 minutes.")
        row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        salt = row["salt"] if row else "00" * 16
        computed = _hash(password, salt)
        valid = row is not None and hmac.compare_digest(computed, row["password_hash"])
        if not valid:
            db.execute("INSERT INTO attempts VALUES (?,?)", (email, now))
        else:
            db.execute("DELETE FROM attempts WHERE email=?", (email,))
    if not valid:
        raise ValueError("Invalid email or password.")
    return {"id": row["id"], "email": email, "issued": now}


def audit(owner, action, target="", detail=None):
    # No prompts, filenames, credentials, or document contents in audit metadata.
    with connection() as db:
        db.execute("INSERT INTO events(owner,action,target,detail,created) VALUES(?,?,?,?,?)",
                   (owner, action, target, json.dumps(detail or {}), time.time()))


def datasets(owner):
    with connection() as db:
        rows = db.execute("SELECT id,name,kind,profile,strategy,status,error,created FROM datasets WHERE owner=? ORDER BY created DESC", (owner,)).fetchall()
    return [dict(r) | {"profile": json.loads(r["profile"])} for r in rows]


def dataset(owner, dataset_id):
    with connection() as db:
        row = db.execute("SELECT * FROM datasets WHERE owner=? AND id=?", (owner, dataset_id)).fetchone()
    if row is None:
        raise ValueError("Dataset is unavailable in this workspace.")
    result = dict(row)
    for field in ("payload", "profile"):
        result[field] = json.loads(result[field])
    return result


def delete_dataset(owner, dataset_id):
    with connection() as db:
        db.execute("DELETE FROM datasets WHERE owner=? AND id=?", (owner, dataset_id))
    audit(owner, "dataset_deleted", dataset_id)


def history(owner, table, limit=100):
    if table not in {"events", "runs", "messages"}:
        raise ValueError("Unsupported history type.")
    with connection() as db:
        return [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE owner=? ORDER BY created DESC LIMIT ?", (owner, limit)).fetchall()]


def save_run(owner, run_id, route, status, duration, steps):
    with connection() as db:
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, owner, route, status, duration, json.dumps(steps), time.time()))


def save_message(owner, question, answer, sources, run_id):
    with connection() as db:
        db.execute("INSERT INTO messages(owner,question,answer,sources,run_id,created) VALUES(?,?,?,?,?,?)",
                   (owner, question, answer, json.dumps(sources), run_id, time.time()))


def feedback(owner, run_id, rating):
    if rating not in {"Helpful", "Needs improvement"}:
        raise ValueError("Invalid rating.")
    with connection() as db:
        if not db.execute("SELECT 1 FROM runs WHERE owner=? AND id=?", (owner, run_id)).fetchone():
            raise ValueError("Run is unavailable.")
        db.execute("INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)", (owner, run_id, rating, time.time()))


def erase_workspace(owner):
    with connection() as db:
        for table in ("feedback", "messages", "runs", "events", "datasets", "migrations", "logistics_links"):
            db.execute(f"DELETE FROM {table} WHERE owner=?", (owner,))


def preferences(owner):
    with connection() as db:
        row = db.execute("SELECT cloud_aggregates FROM preferences WHERE owner=?", (owner,)).fetchone()
    return {"cloud_aggregates": bool(row[0]) if row else False}


def set_preferences(owner, cloud_aggregates):
    with connection() as db:
        db.execute("INSERT OR REPLACE INTO preferences VALUES(?,?)", (owner, int(bool(cloud_aggregates))))
    audit(owner, "privacy_settings_updated", detail={"cloud_aggregates": bool(cloud_aggregates)})


def session_valid(user):
    if not user or time.time() - user.get("issued", 0) >= 8 * 3600:
        return False
    with connection() as db:
        row = db.execute("SELECT password_changed FROM users WHERE id=?", (user.get("id", ""),)).fetchone()
    return row is not None and user["issued"] >= row[0]


def change_password(owner, current_password, new_password):
    if not 12 <= len(new_password) <= 256:
        raise ValueError("Use a password with 12–256 characters.")
    with connection() as db:
        row = db.execute("SELECT email FROM users WHERE id=?", (owner,)).fetchone()
    if row is None:
        raise ValueError("Account not found.")
    login(row[0], current_password)
    salt = secrets.token_hex(16)
    changed = time.time()
    with connection() as db:
        db.execute("UPDATE users SET salt=?,password_hash=?,password_changed=? WHERE id=?", (salt, _hash(new_password, salt), changed, owner))
    audit(owner, "password_changed")
    return changed
