"""Stripe-hosted billing with webhook-authoritative entitlements and owner isolation."""
import os
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from cortex import store

PLAN_NAMES = ('free', 'pro', 'team', 'enterprise', 'starter')
SUB_EVENTS = {'checkout.session.completed', 'checkout.session.async_payment_succeeded',
              'checkout.session.async_payment_failed', 'customer.subscription.created',
              'customer.subscription.updated', 'customer.subscription.deleted',
              'customer.subscription.paused', 'customer.subscription.resumed',
              'invoice.paid', 'invoice.payment_failed', 'invoice.payment_action_required',
              'invoice.finalized', 'invoice.updated', 'invoice.voided', 'invoice.marked_uncollectible',
              'customer.updated', 'payment_method.attached', 'payment_method.detached',
              'payment_method.updated', 'setup_intent.succeeded'}


def plans():
    with store.connection() as db:
        rows = db.execute('SELECT * FROM billing_plans').fetchall()
    result = {}
    for row in rows:
        item = dict(row)
        name = item['name']
        if not item['price_override']:
            item['monthly'] = item['monthly'] or os.getenv(f'STRIPE_PRICE_{name.upper()}_MONTHLY', '') or os.getenv(f'STRIPE_PRICE_{name.upper()}', '')
            item['annual'] = item['annual'] or os.getenv(f'STRIPE_PRICE_{name.upper()}_ANNUAL', '')
        result[name] = item
    return result


def prices():
    return {name: item['monthly'] for name, item in plans().items() if name != 'free'}


def _key():
    import stripe
    if stripe.default_http_client is None:
        stripe.default_http_client = stripe.RequestsClient(timeout=6)
    key = os.getenv('STRIPE_SECRET_KEY', '')
    if key.startswith(('sk_test_', 'rk_test_')):
        return key
    if key.startswith(('sk_live_', 'rk_live_')) and os.getenv('STRIPE_ALLOW_LIVE', 'false').lower() == 'true':
        return key
    raise ValueError('Configure a Stripe test secret key. Live billing requires explicit STRIPE_ALLOW_LIVE=true.')


def _base_url():
    base = os.getenv('BILLING_BASE_URL', 'http://localhost:8503').rstrip('/')
    p = urlparse(base)
    if p.username or p.password or p.query or p.fragment or p.path or not p.hostname or p.scheme not in {'http', 'https'}:
        raise ValueError('Invalid BILLING_BASE_URL; use an origin without a path.')
    if p.scheme != 'https' and p.hostname not in {'localhost', '127.0.0.1'}:
        raise ValueError('Public billing return URLs require HTTPS.')
    return base


def _owner(owner):
    with store.connection() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=?', (owner,)).fetchone():
            raise ValueError('Unknown workspace.')


def account(owner):
    _owner(owner)
    with store.connection() as db:
        row = db.execute('SELECT * FROM billing_accounts WHERE owner=?', (owner,)).fetchone()
    return dict(row) if row else {'owner': owner, 'plan': 'free', 'status': 'not_subscribed', 'updated': 0, 'verified_at': 0}


def customer(owner):
    import stripe
    key = _key()
    current = account(owner)
    if current.get('customer'):
        return current['customer']
    result = stripe.Customer.create(metadata={'workspace_id': owner}, api_key=key,
                                    idempotency_key=f'cortex-customer-{owner}')
    with store.connection() as db:
        db.execute('INSERT OR IGNORE INTO billing_accounts(owner,customer,updated) VALUES(?,?,?)', (owner, result['id'], time.time()))
    return account(owner)['customer']


def checkout(owner, plan, interval='monthly'):
    import stripe
    key = _key()
    price = plans().get(plan, {}).get(interval, '') if interval in {'monthly', 'annual'} and plan != 'free' else ''
    if not re.fullmatch(r'price_[A-Za-z0-9]+', price):
        raise ValueError('This plan has no server-configured Stripe price ID.')
    current = account(owner)
    if current['status'] not in {'not_subscribed', 'unpaid', 'canceled', 'incomplete_expired'} or (current.get('subscription') and current['status'] == 'unpaid'):
        raise ValueError('Manage the existing subscription through the billing portal.')
    cid = customer(owner)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        pending = db.execute('SELECT * FROM billing_checkouts WHERE owner=? AND expires>?', (owner, time.time())).fetchone()
        if pending and pending['session_id']:
            existing = stripe.checkout.Session.retrieve(pending['session_id'], api_key=key)
            if existing['status'] == 'open':
                if pending['plan'] != plan or pending['interval'] != interval:
                    raise ValueError('An unfinished checkout exists. Complete or expire it before selecting another plan.')
                return {'url': pending['url'], 'test_mode': key.startswith(('sk_test_', 'rk_test_'))}
            if existing['status'] == 'complete':
                raise ValueError('Checkout completed. Wait for the verified webhook; do not pay again.')
        # Check Stripe even when a webhook was delayed or local status is stale.
        # A new customer has no subscription yet; existing customers must reconcile.
        if current.get('customer'):
            remote = _current_subscription(cid)
            if remote['subscription'] and remote['status'] not in {'canceled', 'incomplete_expired'}:
                raise ValueError('Manage the existing subscription through the billing portal.')
        result = stripe.checkout.Session.create(mode='subscription', customer=cid,
            line_items=[{'price': price, 'quantity': 1}], client_reference_id=owner,
            subscription_data={'metadata': {'workspace_id': owner}},
            success_url=_base_url() + '/workspace/settings/billing?checkout=returned',
            cancel_url=_base_url() + '/pricing?checkout=cancelled', api_key=key,
            idempotency_key=f'cortex-checkout-{owner}-{plan}-{interval}-{int(time.time()) // 600}')
        db.execute('INSERT OR REPLACE INTO billing_checkouts VALUES(?,?,?,?,?,?)',
            (owner, plan, interval, result.get('id', ''), result['url'], result.get('expires_at', time.time()+86400)))
    store.audit(owner, 'billing_checkout_created', detail={'plan': plan, 'interval': interval, 'test_mode': key.startswith(('sk_test_', 'rk_test_'))})
    return {'url': result['url'], 'test_mode': key.startswith(('sk_test_', 'rk_test_'))}


def portal(owner, flow=None):
    import stripe
    cid = customer(owner)
    options = {}
    if os.getenv('STRIPE_PORTAL_CONFIGURATION'):
        options['configuration'] = os.environ['STRIPE_PORTAL_CONFIGURATION']
    if flow == 'payment_method_update':
        options['flow_data'] = {'type': flow, 'after_completion': {'type': 'redirect', 'redirect': {'return_url': _base_url() + '/workspace/settings/billing/payment-methods'}}}
    elif flow is not None:
        raise ValueError('Unsupported billing portal flow.')
    result = stripe.billing_portal.Session.create(customer=cid,
        return_url=_base_url() + '/workspace/settings/billing', api_key=_key(), **options)
    store.audit(owner, 'billing_portal_created')
    return {'url': result['url']}


def _current_subscription(cid):
    import stripe
    result = stripe.Subscription.list(customer=cid, status='all', limit=100, api_key=_key())
    if result.get('has_more'):
        raise ValueError('More than 100 subscriptions require operator reconciliation.')
    configured = {item[interval]: (name, interval) for name, item in plans().items()
                  for interval in ('monthly', 'annual') if item[interval] and name != 'free'}
    choices = []
    for sub in result['data']:
        for item in sub.get('items', {}).get('data', []):
            price = item.get('price', {})
            if price.get('id') in configured:
                choices.append((sub, item, price, configured[price['id']]))
    if not choices:
        return {'subscription': '', 'plan': 'free', 'status': 'not_subscribed', 'period_start': 0, 'period_end': 0,
                'price_id': '', 'product_id': '', 'interval': '', 'cancel_at_period_end': 0}
    sub, item, price, (name, interval) = max(choices, key=lambda v: (v[0].get('status') in {'active', 'trialing'}, v[0].get('created', 0)))
    return {'subscription': sub['id'], 'plan': name if sub['status'] in {'active', 'trialing'} else 'free',
            'status': sub['status'], 'price_id': price['id'], 'product_id': price.get('product', ''), 'interval': interval,
            'period_start': item.get('current_period_start', sub.get('current_period_start', 0)),
            'period_end': item.get('current_period_end', sub.get('current_period_end', 0)),
            'cancel_at_period_end': int(bool(sub.get('cancel_at_period_end')))}


def _persist(db, owner, current, verified=False):
    fields = ['subscription', 'plan', 'status', 'price_id', 'product_id', 'interval', 'period_start', 'period_end', 'cancel_at_period_end']
    fields = [f for f in fields if f in current]
    db.execute('UPDATE billing_accounts SET ' + ','.join(f + '=?' for f in fields) + ',updated=?' + (',verified_at=?' if verified else '') + ' WHERE owner=?',
               [current[f] for f in fields] + [time.time()] + ([time.time()] if verified else []) + [owner])


def refresh(owner):
    cid = account(owner).get('customer')
    if not cid:
        raise ValueError('No Stripe customer is linked to this workspace.')
    current = _current_subscription(cid)
    with store.connection() as db:
        previous = db.execute('SELECT * FROM billing_accounts WHERE owner=?', (owner,)).fetchone()
        _persist(db, owner, current)
        # Refresh may revoke access, but never activate or elevate paid features.
        if any(current.get(k) != previous[k] for k in ('subscription', 'plan', 'status', 'period_end')):
            db.execute('UPDATE billing_accounts SET verified_at=0 WHERE owner=?', (owner,))
    store.audit(owner, 'billing_reconciled', detail={'plan': current['plan'], 'status': current['status']})
    return current


def _methods(cid):
    import stripe
    obj = stripe.Customer.retrieve(cid, api_key=_key())
    default = obj.get('invoice_settings', {}).get('default_payment_method') or ''
    if isinstance(default, dict):
        default = default['id']
    result = stripe.PaymentMethod.list(customer=cid, type='card', limit=100, api_key=_key())
    if result.get('has_more'):
        raise ValueError('More than 100 cards require Stripe portal management.')
    return default, [{'id': m['id'], 'brand': m['card']['brand'], 'last4': m['card']['last4'],
                      'exp_month': m['card']['exp_month'], 'exp_year': m['card']['exp_year'],
                      'is_default': int(m['id'] == default)} for m in result['data']]


def payment_methods(owner):
    cid = account(owner).get('customer')
    if not cid:
        return []
    default, methods = _methods(cid)
    with store.connection() as db:
        db.execute('DELETE FROM billing_methods WHERE owner=?', (owner,))
        db.executemany('INSERT INTO billing_methods VALUES(?,?,?,?,?,?,?)',
            [(m['id'], owner, m['brand'], m['last4'], m['exp_month'], m['exp_year'], m['is_default']) for m in methods])
        db.execute('UPDATE billing_accounts SET default_method=? WHERE owner=?', (default, owner))
    return methods


def default_method(owner, method_id):
    import stripe
    methods = payment_methods(owner)
    if not any(m['id'] == method_id for m in methods):
        raise ValueError('Payment method does not belong to this workspace.')
    current = account(owner)
    # Customer and subscription defaults must agree for recurring invoices.
    stripe.Customer.modify(current['customer'], invoice_settings={'default_payment_method': method_id},
        api_key=_key(), idempotency_key=f'default-{owner}-{method_id}-{int(time.time()) // 60}')
    if current.get('subscription'):
        stripe.Subscription.modify(current['subscription'], default_payment_method=method_id,
            api_key=_key(), idempotency_key=f'sub-default-{owner}-{method_id}-{int(time.time()) // 60}')
    store.audit(owner, 'billing_default_method_changed', method_id)
    return payment_methods(owner)


def remove_method(owner, method_id, confirmed=False):
    import stripe
    methods = payment_methods(owner)
    current = account(owner)
    method = next((m for m in methods if m['id'] == method_id), None)
    if not method or not confirmed:
        raise ValueError('Confirm removal of a workspace-owned payment method.')
    if method['is_default'] or (len(methods) <= 1 and current['status'] not in {'canceled', 'not_subscribed', 'incomplete_expired'}):
        raise ValueError('Keep a payment method for the subscription; set another default before removal.')
    if current.get('subscription'):
        sub = stripe.Subscription.retrieve(current['subscription'], api_key=_key())
        if sub.get('customer') != current['customer'] or sub.get('default_payment_method') == method_id:
            raise ValueError('Set another subscription payment method before removal.')
    stripe.PaymentMethod.detach(method_id, api_key=_key(),
        idempotency_key=f'detach-{owner}-{method_id}')
    store.audit(owner, 'billing_method_removed', method_id)
    return payment_methods(owner)


def _safe_url(url):
    p = urlparse(url or '')
    return url if p.scheme == 'https' and p.hostname and (p.hostname == 'stripe.com' or p.hostname.endswith('.stripe.com')) and not p.username else ''


def _save_invoice(db, owner, invoice):
    payment = invoice.get('payment_intent')
    if not payment:
        payments = (invoice.get('payments') or {}).get('data', [])
        if payments:
            details = payments[0].get('payment', {})
            payment = details.get('payment_intent') or payments[0].get('id', '')
    if isinstance(payment, dict):
        payment = payment.get('id', '')
    db.execute('INSERT INTO billing_invoices VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, amount_due=excluded.amount_due, amount_paid=excluded.amount_paid, hosted_url=excluded.hosted_url, pdf_url=excluded.pdf_url, payment=excluded.payment WHERE owner=excluded.owner',
        (invoice['id'], owner, invoice.get('status') or 'draft', invoice.get('currency', ''), invoice.get('amount_due', 0),
         invoice.get('amount_paid', 0), _safe_url(invoice.get('hosted_invoice_url')), _safe_url(invoice.get('invoice_pdf')),
         payment if isinstance(payment, str) else '', invoice.get('created', time.time())))


def invoices(owner, after=None):
    import stripe
    cid = account(owner).get('customer')
    if not cid:
        return {'data': [], 'has_more': False}
    kwargs = {'starting_after': after} if after else {}
    if after:
        with store.connection() as db:
            if not db.execute('SELECT 1 FROM billing_invoices WHERE owner=? AND id=?', (owner, after)).fetchone():
                raise ValueError('Invalid invoice cursor.')
    result = stripe.Invoice.list(customer=cid, limit=25, api_key=_key(), **kwargs)
    with store.connection() as db:
        for invoice in result['data']:
            if invoice.get('customer') != cid:
                raise ValueError('Invoice customer mismatch.')
            _save_invoice(db, owner, invoice)
        ids = [i['id'] for i in result['data']]
        rows = [dict(db.execute('SELECT * FROM billing_invoices WHERE owner=? AND id=?', (owner, iid)).fetchone()) for iid in ids]
    return {'data': rows, 'has_more': bool(result.get('has_more'))}


def webhook(raw, signature):
    import stripe
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    if not secret:
        raise ValueError('Stripe webhook secret is not configured.')
    if len(raw) > 256 * 1024:
        raise ValueError('Webhook body is too large.')
    try:
        event = stripe.Webhook.construct_event(raw, signature, secret, tolerance=300)
    except Exception:
        raise ValueError('Invalid Stripe webhook signature or payload.') from None
    if bool(event.get('livemode')) != _key().startswith(('sk_live_', 'rk_live_')):
        raise ValueError('Webhook mode does not match this deployment.')
    with store.connection() as db:
        # Serialize reconciliation across workers, including provider reads, so
        # an older snapshot cannot overwrite a newer webhook commit.
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM billing_events WHERE id=?', (event['id'],)).fetchone():
            return {'status': 'duplicate'}
        obj = event['data']['object']
        cid = obj.get('customer', '')
        row = db.execute('SELECT owner FROM billing_accounts WHERE customer=?', (cid,)).fetchone()
        current = _current_subscription(cid) if row and event['type'] in SUB_EVENTS else None
        if current:
            _persist(db, row[0], current, verified=True)
            if event['type'].startswith('invoice.') and obj.get('id'):
                # Re-fetch to tolerate reversed invoice events as well.
                invoice = stripe.Invoice.retrieve(obj['id'], api_key=_key())
                if invoice.get('customer') != cid:
                    raise ValueError('Invoice customer mismatch.')
                _save_invoice(db, row[0], invoice)
            db.execute('INSERT INTO events(owner,action,target,detail,created) VALUES(?,?,?,?,?)',
                (row[0], 'billing_webhook_reconciled', event['id'], '{}', time.time()))
        db.execute('INSERT INTO billing_events VALUES(?,?)', (event['id'], time.time()))
    return {'status': 'processed' if current else 'ignored'}


def limits(owner, db=None):
    def read(conn):
        row = conn.execute('SELECT * FROM billing_accounts WHERE owner=?', (owner,)).fetchone()
        name = 'free'
        # Expiry is enforced even if a cancellation webhook never arrives.
        if row and row['verified_at'] and row['status'] in {'active', 'trialing'} and row['period_end'] > time.time():
            name = row['plan']
        plan = conn.execute('SELECT * FROM billing_plans WHERE name=?', (name,)).fetchone()
        return dict(plan)
    if db is not None:
        return read(db)
    _owner(owner)
    with store.connection() as conn:
        return read(conn)


def usage(owner):
    _owner(owner)
    period = datetime.now(timezone.utc).strftime('%Y-%m')
    with store.connection() as db:
        used = db.execute('SELECT COUNT(*) FROM billing_usage WHERE owner=? AND period=?', (owner, period)).fetchone()[0]
        files, size = db.execute('SELECT COUNT(*),COALESCE(SUM(LENGTH(raw)),0) FROM datasets WHERE owner=?', (owner,)).fetchone()
    return {'period_utc': period, 'ai_requests': used, 'files': files, 'storage_bytes': size, 'limits': limits(owner),
            'tokens': None, 'cost': None, 'notice': 'Requests count Carol custom workflows, not FAQ or billing actions. Tokens and provider cost are not measured; this is not metered Stripe invoicing.'}


def reserve_request(owner):
    _owner(owner)
    request_id = secrets.token_hex(16)
    period = datetime.now(timezone.utc).strftime('%Y-%m')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        cap = limits(owner, db)['ai_requests']
        used = db.execute('SELECT COUNT(*) FROM billing_usage WHERE owner=? AND period=?', (owner, period)).fetchone()[0]
        if used >= cap:
            raise ValueError('Monthly AI request allowance reached. Review Billing → Usage.')
        db.execute('INSERT INTO billing_usage VALUES(?,?,?,?,?)', (request_id, owner, period, 'reserved', time.time()))
    return request_id


def finish_request(owner, request_id, failed=False):
    with store.connection() as db:
        # Failed requests count: they may already have consumed provider resources.
        db.execute('UPDATE billing_usage SET state=? WHERE id=? AND owner=?', ('failed' if failed else 'completed', request_id, owner))


def configure_plan(actor, name, monthly, annual, files, storage_mb, ai_requests):
    from cortex.security import require_admin
    require_admin(actor)
    if name not in PLAN_NAMES or name == 'starter':
        raise ValueError('Unknown editable plan.')
    if any(v and not re.fullmatch(r'price_[A-Za-z0-9]+', v) for v in (monthly, annual)):
        raise ValueError('Invalid Stripe price ID.')
    if any(not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 100000 for v in (files, storage_mb, ai_requests)):
        raise ValueError('Limits must be integers between 1 and 100000.')
    if name == 'free' and (monthly or annual):
        raise ValueError('Free cannot reference a paid price.')
    if monthly or annual:
        import stripe
        for interval, price_id in [('month', monthly), ('year', annual)]:
            if not price_id:
                continue
            price = stripe.Price.retrieve(price_id, api_key=_key())
            if not price.get('active') or price.get('recurring', {}).get('interval') != interval or price.get('recurring', {}).get('interval_count') != 1:
                raise ValueError('Use an active recurring monthly or annual price.')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        # Keep price-to-plan mapping unambiguous.
        existing = plans()
        previous = existing[name]
        for old, new in [(previous['monthly'], monthly), (previous['annual'], annual)]:
            if old and old != new and db.execute("SELECT 1 FROM billing_accounts WHERE price_id=? AND status NOT IN ('canceled','incomplete_expired')", (old,)).fetchone():
                raise ValueError('This price has current subscriptions. Migrate them before replacing its mapping.')
        for other, item in existing.items():
            if other != name and any(p and p in {item['monthly'], item['annual']} for p in (monthly, annual)):
                raise ValueError('A price is already mapped to another plan.')
        db.execute('UPDATE billing_plans SET price_override=1,monthly=?,annual=?,files=?,storage_mb=?,ai_requests=? WHERE name=?',
            (monthly, annual, files, storage_mb, ai_requests, name))
    store.audit(actor, 'billing_plan_configured', name)


def admin_accounts(actor):
    from cortex.security import require_admin
    require_admin(actor)
    with store.connection() as db:
        return [dict(r) for r in db.execute('SELECT u.id,u.email,b.customer,b.subscription,b.plan,b.status,b.period_end,b.verified_at FROM users u LEFT JOIN billing_accounts b ON b.owner=u.id ORDER BY u.created DESC')]


def admin_cancel(actor, target, confirmed=False):
    from cortex.security import require_admin
    require_admin(actor)
    if not confirmed:
        raise ValueError('Explicit cancellation confirmation required.')
    import stripe
    current = account(target)
    if not current.get('subscription'):
        raise ValueError('No subscription exists for that customer.')
    # Confirm immutable customer ownership from Stripe before modifying.
    sub = stripe.Subscription.retrieve(current['subscription'], api_key=_key())
    if sub.get('customer') != current['customer']:
        raise ValueError('Subscription customer mismatch.')
    stripe.Subscription.modify(current['subscription'], cancel_at_period_end=True, api_key=_key(),
        idempotency_key=f'admin-cancel-{target}-{current["subscription"]}')
    store.audit(actor, 'billing_admin_cancel_scheduled', target)
