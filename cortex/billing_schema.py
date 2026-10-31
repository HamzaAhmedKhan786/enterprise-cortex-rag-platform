"""Idempotent billing migration. Stores references and safe summaries, never PAN/CVV."""
from cortex import store


def migrate():
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS billing_plans (
          name TEXT PRIMARY KEY, monthly TEXT NOT NULL DEFAULT '', annual TEXT NOT NULL DEFAULT '',
          files INTEGER NOT NULL, storage_mb INTEGER NOT NULL, ai_requests INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS billing_invoices (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
          currency TEXT NOT NULL, amount_due INTEGER NOT NULL, amount_paid INTEGER NOT NULL,
          hosted_url TEXT NOT NULL, pdf_url TEXT NOT NULL, payment TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS billing_methods (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), brand TEXT NOT NULL,
          last4 TEXT NOT NULL, exp_month INTEGER NOT NULL, exp_year INTEGER NOT NULL,
          is_default INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS billing_sessions (
          digest TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL,
          issued REAL NOT NULL, expires REAL NOT NULL, verified REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS billing_usage (
          id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), period TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'reserved', created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS billing_usage_period ON billing_usage(owner,period);
        CREATE TABLE IF NOT EXISTS billing_admins (
          owner TEXT PRIMARY KEY REFERENCES users(id), created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS billing_checkouts (
          owner TEXT PRIMARY KEY REFERENCES users(id), plan TEXT NOT NULL,
          interval TEXT NOT NULL, session_id TEXT NOT NULL, url TEXT NOT NULL,
          expires REAL NOT NULL);
        ''')
        db.execute('BEGIN IMMEDIATE')
        if 'price_override' not in {r[1] for r in db.execute('PRAGMA table_info(billing_plans)')}:
            db.execute('ALTER TABLE billing_plans ADD COLUMN price_override INTEGER NOT NULL DEFAULT 0')
        columns = {r[1] for r in db.execute('PRAGMA table_info(billing_accounts)')}
        for name, definition in {
            'price_id': "TEXT NOT NULL DEFAULT ''", 'product_id': "TEXT NOT NULL DEFAULT ''",
            'interval': "TEXT NOT NULL DEFAULT ''", 'period_start': 'REAL NOT NULL DEFAULT 0',
            'period_end': 'REAL NOT NULL DEFAULT 0', 'cancel_at_period_end': 'INTEGER NOT NULL DEFAULT 0',
            'verified_at': 'REAL NOT NULL DEFAULT 0', 'default_method': "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in columns:
                db.execute(f'ALTER TABLE billing_accounts ADD COLUMN {name} {definition}')
        db.executemany('INSERT OR IGNORE INTO billing_plans(name,files,storage_mb,ai_requests) VALUES(?,?,?,?)',
                       [('free',50,100,100),('pro',100,500,1000),('team',500,2000,5000),
                        ('enterprise',2000,10000,20000),('starter',100,500,1000)])
