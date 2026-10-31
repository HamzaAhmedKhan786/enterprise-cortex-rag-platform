"""Stripe-hosted subscriptions. No card data, price setting or AI payment decisions."""
import os
import re
import time
from urllib.parse import urlparse

from cortex import store


def prices():
    return {p: os.getenv(f"STRIPE_PRICE_{p.upper()}", "") for p in ("starter", "team")}


def _key():
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if key.startswith(("sk_test_", "rk_test_")):
        return key
    if key.startswith(("sk_live_", "rk_live_")) and os.getenv("STRIPE_ALLOW_LIVE", "false").lower() == "true":
        return key
    raise ValueError("Configure a Stripe test secret key. Live billing requires explicit STRIPE_ALLOW_LIVE=true.")


def _base_url():
    base = os.getenv("APP_BASE_URL", "http://localhost:8501").rstrip("/")
    p = urlparse(base)
    if p.username or p.password or p.query or p.fragment or not p.hostname or p.scheme not in {"http", "https"}:
        raise ValueError("Invalid APP_BASE_URL.")
    if p.scheme != "https" and p.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Public billing return URLs require HTTPS.")
    return base


def account(owner):
    with store.connection() as db:
        row = db.execute("SELECT * FROM billing_accounts WHERE owner=?", (owner,)).fetchone()
    return dict(row) if row else {"owner": owner, "plan": "free", "status": "not_subscribed", "updated": 0}


def checkout(owner, plan):
    key = _key()
    price = prices().get(plan, "")
    if not re.fullmatch(r"price_[A-Za-z0-9]+", price):
        raise ValueError("This plan has no server-configured Stripe price ID.")
    import stripe
    current = account(owner)
    if current["status"] in {"active", "trialing"}:
        raise ValueError("Manage the existing subscription through the billing portal.")
    customer = current.get("customer")
    if not customer:
        result = stripe.Customer.create(metadata={"workspace_id": owner}, api_key=key, idempotency_key=f"cortex-customer-{owner}")
        customer = result["id"]
        with store.connection() as db:
            db.execute("INSERT OR IGNORE INTO billing_accounts(owner,customer,updated) VALUES(?,?,?)", (owner, customer, time.time()))
        customer = account(owner)["customer"]
    result = stripe.checkout.Session.create(mode="subscription", customer=customer,
        line_items=[{"price": price, "quantity": 1}], client_reference_id=owner,
        success_url=_base_url() + "/?billing=success", cancel_url=_base_url() + "/?billing=cancelled",
        api_key=key, idempotency_key=f"cortex-checkout-{owner}-{plan}-{int(time.time()) // 600}")
    store.audit(owner, "billing_checkout_created", detail={"plan": plan, "test_mode": key.startswith(("sk_test_", "rk_test_"))})
    return {"url": result["url"], "test_mode": key.startswith(("sk_test_", "rk_test_"))}


def portal(owner):
    import stripe
    key = _key()
    customer = account(owner).get("customer")
    if not customer:
        raise ValueError("Create a checkout session before opening the billing portal.")
    result = stripe.billing_portal.Session.create(customer=customer, return_url=_base_url(), api_key=key)
    store.audit(owner, "billing_portal_created")
    return {"url": result["url"]}


def _current_subscription(customer):
    import stripe
    result = stripe.Subscription.list(customer=customer, status="all", limit=100, api_key=_key())
    if result.get("has_more"):
        raise ValueError("More than 100 subscriptions require operator reconciliation.")
    choices = []
    configured = {value: name for name, value in prices().items() if value}
    for sub in result["data"]:
        items = sub.get("items", {}).get("data", [])
        plan = next((configured.get(item.get("price", {}).get("id")) for item in items if configured.get(item.get("price", {}).get("id"))), None)
        if plan:
            choices.append((sub.get("status") in {"active", "trialing"}, sub.get("created", 0), sub, plan))
    if not choices:
        return {"subscription": "", "plan": "free", "status": "not_subscribed"}
    _, _, sub, plan = max(choices, key=lambda v: (v[0], v[1]))
    active = sub["status"] in {"active", "trialing"}
    return {"subscription": sub["id"], "plan": plan if active else "free", "status": sub["status"]}


def refresh(owner):
    customer = account(owner).get("customer")
    if not customer:
        raise ValueError("No Stripe customer is linked to this workspace.")
    current = _current_subscription(customer)
    with store.connection() as db:
        db.execute("UPDATE billing_accounts SET subscription=?,plan=?,status=?,updated=? WHERE owner=?",
                   (current["subscription"], current["plan"], current["status"], time.time(), owner))
    store.audit(owner, "billing_reconciled", detail={"plan": current["plan"], "status": current["status"]})
    return current


def webhook(raw, signature):
    import stripe
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise ValueError("Stripe webhook secret is not configured.")
    if len(raw) > 256 * 1024:
        raise ValueError("Webhook body is too large.")
    try:
        event = stripe.Webhook.construct_event(raw, signature, secret, tolerance=300)
    except Exception:
        raise ValueError("Invalid Stripe webhook signature or payload.") from None
    if bool(event.get("livemode")) != (_key().startswith(("sk_live_", "rk_live_"))):
        raise ValueError("Webhook mode does not match this deployment.")
    with store.connection() as db:
        if db.execute("SELECT 1 FROM billing_events WHERE id=?", (event["id"],)).fetchone():
            return {"status": "duplicate"}
    supported = {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}
    obj = event["data"]["object"]
    with store.connection() as db:
        row = db.execute("SELECT owner FROM billing_accounts WHERE customer=?", (obj.get("customer", ""),)).fetchone()
    # Re-fetch authoritative state: replayed/out-of-order event payloads cannot
    # reactivate canceled subscriptions, and metadata cannot select an owner.
    current = _current_subscription(obj["customer"]) if row and event["type"] in supported else None
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM billing_events WHERE id=?", (event["id"],)).fetchone():
            return {"status": "duplicate"}
        if current:
            db.execute("UPDATE billing_accounts SET subscription=?,plan=?,status=?,updated=? WHERE owner=?",
                       (current["subscription"], current["plan"], current["status"], time.time(), row[0]))
        db.execute("INSERT INTO billing_events VALUES(?,?)", (event["id"], time.time()))
    if current:
        store.audit(row[0], "billing_webhook_reconciled", detail={"status": current["status"], "plan": current["plan"]})
    return {"status": "processed" if current else "ignored"}
