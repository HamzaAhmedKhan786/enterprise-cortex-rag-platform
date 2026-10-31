"""Assigned RouteMind plan polling with workspace-local cached snapshots."""
import json
import re
import time

from cortex import integrations, security, store


def assign(actor, owner, plan_id):
    security.require_admin(actor)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", plan_id):
        raise ValueError("Invalid RouteMind plan ID.")
    with store.connection() as db:
        if not db.execute("SELECT 1 FROM users WHERE id=?", (owner,)).fetchone():
            raise ValueError("Target workspace account was not found.")
        db.execute("INSERT OR IGNORE INTO logistics_links(owner,plan_id) VALUES(?,?)", (owner, plan_id))
    store.audit(actor, "logistics_plan_assigned", detail={"assigned": True})


def links(owner):
    with store.connection() as db:
        rows = db.execute("SELECT plan_id,snapshot,fetched FROM logistics_links WHERE owner=? ORDER BY plan_id", (owner,)).fetchall()
    return [dict(row) | {"snapshot": json.loads(row["snapshot"])} for row in rows]


def fetch(owner, plan_id):
    if plan_id not in {row["plan_id"] for row in links(owner)}:
        raise ValueError("This plan is not assigned to your workspace.")
    result = integrations.logistics_plan(plan_id)
    with store.connection() as db:
        db.execute("UPDATE logistics_links SET snapshot=?,fetched=? WHERE owner=? AND plan_id=?", (json.dumps(result), time.time(), owner, plan_id))
    store.audit(owner, "logistics_live_snapshot", detail={"routes": len(result["routes"])})
    return result
