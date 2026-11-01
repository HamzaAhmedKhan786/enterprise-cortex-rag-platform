"""Additive account/RBAC migration. Existing PBKDF2 hashes and owner IDs stay intact."""
import os
import time
from cortex import store


def migrate():
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS profiles (
          owner TEXT PRIMARY KEY REFERENCES users(id), full_name TEXT NOT NULL DEFAULT '',
          company TEXT NOT NULL DEFAULT '', job_title TEXT NOT NULL DEFAULT '',
          country TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL DEFAULT 'UTC');
        CREATE TABLE IF NOT EXISTS platform_roles (
          owner TEXT PRIMARY KEY REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('super_admin','admin')));
        CREATE TABLE IF NOT EXISTS auth_steps (
          digest TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), issued REAL NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS email_tokens (
          digest TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), purpose TEXT NOT NULL,
          email TEXT NOT NULL, expires REAL NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS email_attempts (digest TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_bridges (
          digest TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), destination TEXT NOT NULL,
          issued REAL NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS organizations (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS memberships (
          organization TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          owner TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('owner','manager','member','viewer')),
          PRIMARY KEY(organization,owner));
        CREATE TABLE IF NOT EXISTS invitations (
          digest TEXT PRIMARY KEY, organization TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          email TEXT NOT NULL, role TEXT NOT NULL, inviter TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS teams (
          id TEXT PRIMARY KEY, organization TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
          name TEXT NOT NULL, UNIQUE(id,organization), UNIQUE(organization,name));
        CREATE TABLE IF NOT EXISTS team_members (
          team TEXT NOT NULL, organization TEXT NOT NULL, owner TEXT NOT NULL,
          PRIMARY KEY(team,owner), FOREIGN KEY(team,organization) REFERENCES teams(id,organization) ON DELETE CASCADE,
          FOREIGN KEY(organization,owner) REFERENCES memberships(organization,owner) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS organization_datasets (
          dataset TEXT PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
          organization TEXT NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT);
        ''')
        db.execute('BEGIN IMMEDIATE')
        fields={r[1] for r in db.execute('PRAGMA table_info(users)')}
        for name,definition in {'status':"TEXT NOT NULL DEFAULT 'active'",'last_login':'REAL NOT NULL DEFAULT 0',
            'sessions_revoked':'REAL NOT NULL DEFAULT 0','email_verified':'REAL NOT NULL DEFAULT 0',
            'argon2_hash':"TEXT NOT NULL DEFAULT ''"}.items():
            if name not in fields:
                db.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
        for table,columns in [('billing_sessions',{'admin_proof':"TEXT NOT NULL DEFAULT ''"}),
                              ('messages',{'organization':"TEXT NOT NULL DEFAULT ''"}),
                              ('runs',{'organization':"TEXT NOT NULL DEFAULT ''"})]:
            existing={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
            for name,definition in columns.items():
                if name not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        primary=os.getenv('CORTEX_ADMIN_USER_ID','')
        if primary and db.execute("SELECT 1 FROM users WHERE id=? AND status='active'",(primary,)).fetchone():
            previous=db.execute('SELECT role FROM platform_roles WHERE owner=?',(primary,)).fetchone()
            if not previous or previous[0]!='super_admin':
                db.execute("INSERT INTO platform_roles VALUES(?,'super_admin') ON CONFLICT(owner) DO UPDATE SET role='super_admin'",(primary,))
                db.execute("INSERT INTO events(owner,action,target,detail,created) VALUES(?,'primary_admin_bootstrapped',?,'{}',?)",(primary,primary,time.time()))
