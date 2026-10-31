"""Authenticated server-rendered billing pages. Card collection stays on Stripe."""
import hashlib
import hmac
import html
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from cortex import billing, store

router = APIRouter()
COOKIE = 'cortex_billing_session'
BASE = '/workspace/settings/billing'
PATHS = [('/pricing','Pricing'),(BASE,'Overview'),(BASE+'/payment-methods','Payment methods'),
         (BASE+'/invoices','Invoices'),(BASE+'/usage','Usage'),('/admin/billing','Admin')]
e = lambda value: html.escape(str(value), quote=True)


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _cookie(response, value):
    response.set_cookie(COOKIE, value, max_age=8*3600, httponly=True,
                        secure=billing._base_url().startswith('https://'), samesite='lax', path='/')
    return response


def _session(request):
    store.initialize()
    token = request.cookies.get(COOKIE, '')
    with store.connection() as db:
        row = db.execute('SELECT s.*,u.password_changed FROM billing_sessions s JOIN users u ON u.id=s.owner WHERE digest=?', (_digest(token),)).fetchone()
    if not row or row['expires'] <= time.time() or row['issued'] < row['password_changed']:
        return None
    return dict(row)


def issue_session(owner):
    billing._owner(owner)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = time.time()
    with store.connection() as db:
        db.execute('DELETE FROM billing_sessions WHERE expires<?', (now,))
        db.execute('INSERT INTO billing_sessions(digest,owner,csrf,issued,expires) VALUES(?,?,?,?,?)',
                   (_digest(token), owner, csrf, now, now+8*3600))
    return token


def form(session, action, label, fields=''):
    return f'<form method="post" action="{e(action)}"><input type="hidden" name="csrf" value="{e(session["csrf"])}">{fields}<button>{e(label)}</button></form>'


def page(title, body, session=None, status=200):
    links = ''.join(f'<a href="{path}">{label}</a>' for path,label in PATHS if session or path=='/pricing')
    logout = form(session, '/billing/logout', 'Sign out of billing') if session else '<a href="/billing/login">Sign in</a>'
    response = HTMLResponse(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · Cortex</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f4f7f8;color:#17353e;font:16px system-ui}}header{{padding:20px;background:#102e36;color:white}}header strong{{font-size:25px}}nav{{display:flex;gap:18px;flex-wrap:wrap;margin-top:18px}}nav a{{color:#91dbc8}}main{{max-width:1150px;margin:35px auto;padding:0 22px}}section{{background:white;border:1px solid #dce6e8;border-radius:14px;padding:24px;margin:18px 0}}button,.button{{background:#087f76;border:0;border-radius:8px;color:white;padding:12px 18px;cursor:pointer;display:inline-block}}input,select{{padding:10px;border:1px solid #acbfc4;border-radius:6px;margin:8px;max-width:100%}}label{{display:block}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}.table{{overflow-x:auto}}.notice{{padding:15px;background:#e3f2ee;border-radius:8px}}form{{margin:15px 0}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:15px}}small{{color:#526d75}}a{{color:#087f76}}@media(max-width:600px){{main{{padding:0 12px}}section{{padding:15px}}}}
    </style></head><body><header><strong>◇ Cortex · Billing</strong><nav>{links}</nav></header><main><h1>{e(title)}</h1>{body}{logout}</main></body></html>''', status_code=status)
    # Chrome emits Origin:null for form navigation under no-referrer.
    # Preserve same-origin form origins while withholding external referrers.
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'same-origin','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
    return response


def _protected(request):
    session = _session(request)
    if not session:
        raise HTTPException(401, 'Sign in at /billing/login to access billing.')
    return session


async def _fields(request, session):
    if request.headers.get('origin') not in {None, billing._base_url()}:
        raise HTTPException(403, 'Origin rejected')
    if 'application/x-www-form-urlencoded' not in request.headers.get('content-type',''):
        raise HTTPException(415, 'Expected form submission')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>8192:
            raise HTTPException(413, 'Form too large')
    fields = {k:v[0] for k,v in parse_qs(body.decode(),max_num_fields=25).items()}
    if not hmac.compare_digest(fields.get('csrf',''), session['csrf']):
        raise HTTPException(403, 'Invalid form token')
    return fields


def _admin(session, stepped=True):
    from cortex.security import require_admin
    require_admin(session['owner'])
    # Only an already operator-assigned, immutable account ID can bootstrap.
    with store.connection() as db:
        db.execute('INSERT OR IGNORE INTO billing_admins VALUES(?,?)', (session['owner'],time.time()))
        if not db.execute('SELECT 1 FROM billing_admins WHERE owner=?', (session['owner'],)).fetchone():
            raise ValueError('Billing administrator role required.')
    if stepped and time.time()-session['verified']>600:
        raise ValueError('Admin verification expired. Re-enter your account password.')


@router.get('/billing/login')
def login_page(request: Request):
    token=secrets.token_urlsafe(32)
    body=f'<section><p>Use your Cortex workspace account. This creates a separate, secure billing session.</p><form method="post"><input type="hidden" name="csrf" value="{e(token)}"><label>Email <input name="email" type="email" required autocomplete="username"></label><label>Password <input name="password" type="password" required autocomplete="current-password"></label><button>Sign in to billing</button></form></section>'
    response=page('Sign in to billing',body)
    response.set_cookie('cortex_login_csrf',token,httponly=True,secure=billing._base_url().startswith('https://'),samesite='strict',max_age=600)
    return response


@router.post('/billing/login')
async def login(request: Request):
    store.initialize()
    login_csrf=request.cookies.get('cortex_login_csrf')
    if not login_csrf:
        raise HTTPException(403, 'Open the billing sign-in page before submitting credentials')
    fields=await _fields(request, {'csrf':login_csrf})
    try:
        user=store.login(fields.get('email',''),fields.get('password',''))
        response=_cookie(RedirectResponse(BASE,status_code=303),issue_session(user['id']))
        response.delete_cookie('cortex_login_csrf')
        return response
    except ValueError as exc:
        return page('Sign in failed',f'<p>{e(exc)}</p><a href="/billing/login">Try again</a>',status=401)


@router.post('/billing/logout')
async def logout(request: Request):
    session=_protected(request)
    await _fields(request,session)
    with store.connection() as db:
        db.execute('DELETE FROM billing_sessions WHERE digest=?',(session['digest'],))
    response=RedirectResponse('/billing/login',status_code=303)
    response.delete_cookie(COOKIE)
    return response


@router.get('/pricing')
def pricing(request: Request):
    store.initialize()
    session=_session(request)
    cards=[]
    for name,item in billing.plans().items():
        if name=='starter':
            continue
        actions=''
        for interval in ('monthly','annual'):
            if name=='free':
                continue
            if item[interval] and session:
                fields=f'<input type="hidden" name="plan" value="{name}"><input type="hidden" name="interval" value="{interval}">'
                actions+=form(session,'/billing/actions/checkout','Choose '+interval,fields)
            elif not item[interval]:
                actions+=f'<p>{interval.title()}: price not configured</p>'
        cards.append(f'<section><h2>{e(name.title())}</h2><p>{item["files"]:,} files · {item["storage_mb"]:,} MiB storage</p><p>{item["ai_requests"]:,} custom AI requests / UTC month</p><small>Configured allowances. Exact currency, recurring price and tax are shown by Stripe before purchase.</small>{actions}</section>')
    return page('Plans & pricing','<div class="notice">Test mode is the default. No final prices have been invented. Free requires no payment.</div><div class="cards">'+''.join(cards)+'</div>',session)


def _date(value):
    return datetime.fromtimestamp(value,timezone.utc).strftime('%d %b %Y %H:%M UTC') if value else 'Not available'


@router.get(BASE)
@router.get(BASE+'/payment-methods')
@router.get(BASE+'/invoices')
@router.get(BASE+'/usage')
def billing_page(request: Request):
    session=_session(request)
    if not session:
        return RedirectResponse('/billing/login',status_code=303)
    owner=session['owner']
    current=billing.account(owner)
    path=request.url.path
    title=dict(PATHS).get(path,'Billing')
    try:
        if path.endswith('payment-methods'):
            methods=billing.payment_methods(owner)
            body='<p>Settings → Billing → Payment Methods. Card entry and replacement use Stripe’s secure hosted interface.</p>'
            body+=form(session,'/billing/actions/payment-methods','Add or replace payment method at Stripe')
            if not methods:
                body+='<p>No saved cards. Other payment types and billing details are managed in the Stripe portal.</p>'
            for m in methods:
                fields=f'<input type="hidden" name="method" value="{e(m["id"])}">'
                body+=f'<section><h2>{e(m["brand"])} •••• {e(m["last4"])}</h2><p>Expires {m["exp_month"]:02d}/{m["exp_year"]} '+(' · Default' if m['is_default'] else '')+'</p>'
                if not m['is_default']:
                    body+=form(session,'/billing/actions/default-method','Set as default',fields)
                    body+=form(session,'/billing/actions/remove-method','Remove eligible card',fields+'<label><input type="checkbox" name="confirmed" value="yes" required>Confirm removal</label>')
                body+='</section>'
            body+=form(session,'/billing/actions/portal','Manage all payment methods and billing details at Stripe')
        elif path.endswith('invoices'):
            result=billing.invoices(owner,request.query_params.get('after'))
            body='<p>Invoice amounts are in Stripe minor currency units. Download links go directly to Stripe.</p><div class="table"><table><tr><th>Invoice</th><th>Status</th><th>Amount paid</th><th>Created</th><th>Documents</th></tr>'
            for invoice in result['data']:
                links=' '.join(f'<a href="{e(invoice[k])}" rel="noreferrer">{label}</a>' for k,label in [('hosted_url','View / pay'),('pdf_url','Download PDF')] if invoice[k])
                body+=f'<tr><td>{e(invoice["id"])}</td><td>{e(invoice["status"])}</td><td>{invoice["amount_paid"]} {e(invoice["currency"].upper())} minor units</td><td>{_date(invoice["created"])}</td><td>{links}</td></tr>'
            body+='</table></div>'
            if result['has_more'] and result['data']:
                body+=f'<a href="?{urlencode({"after":result["data"][-1]["id"]})}">Next invoices</a>'
        elif path.endswith('usage'):
            usage=billing.usage(owner)
            body=f'<section><h2>{e(usage["period_utc"])} · UTC calendar month</h2><p>Custom AI requests: {usage["ai_requests"]} / {usage["limits"]["ai_requests"]}</p><p>Files: {usage["files"]} / {usage["limits"]["files"]}</p><p>Storage: {usage["storage_bytes"] / 1048576:.2f} / {usage["limits"]["storage_mb"]} MiB</p><p>{e(usage["notice"])}</p><p>Token usage and provider cost: not available.</p></section>'
        else:
            body=f'<section><h2>{e(current["plan"].title())} · {e(current["status"])}</h2><p>Billing cycle: {e(current.get("interval") or "None")}</p><p>Current period: {_date(current.get("period_start"))} → {_date(current.get("period_end"))}</p><p>Scheduled cancellation: {"Yes" if current.get("cancel_at_period_end") else "No"}</p><p>Paid entitlements: {e(billing.limits(owner)["name"])}</p></section>'
            with store.connection() as db:
                card=db.execute('SELECT brand,last4,exp_month,exp_year FROM billing_methods WHERE owner=? AND is_default=1',(owner,)).fetchone()
            body+=f'<p>Default card: {e(card["brand"])} •••• {e(card["last4"])} · {card["exp_month"]:02d}/{card["exp_year"]}</p>' if card else '<p>Payment method: open Payment Methods to retrieve the current Stripe summary.</p>'
            allowance=billing.limits(owner)
            body+=f'<p>Usage limits: {allowance["files"]:,} files · {allowance["storage_mb"]:,} MiB · {allowance["ai_requests"]:,} custom AI requests / UTC month.</p>'
            body+='<p class="notice">Checkout return pages never activate paid features. Verified webhooks authorize benefits through the current billing period. A status refresh cannot grant paid access.</p>'
            body+=form(session,'/billing/actions/portal','Upgrade, downgrade, cancel or edit billing details at Stripe')
        return page(title,body,session)
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else 'Stripe is unavailable or not configured. Your billing state was not changed. Check server configuration.'
        return page(title,f'<p class="notice">{e(message)}</p><a href="{BASE}">Billing overview</a>',session,status=503)


@router.post('/billing/actions/{action}')
async def action(action: str, request: Request):
    session=_protected(request)
    fields=await _fields(request,session)
    owner=session['owner']
    try:
        if action=='checkout':
            result=billing.checkout(owner,fields.get('plan',''),fields.get('interval',''))
        elif action in {'portal','payment-methods'}:
            result=billing.portal(owner,'payment_method_update' if action=='payment-methods' else None)
        elif action=='default-method':
            billing.default_method(owner,fields.get('method',''))
            return RedirectResponse(BASE+'/payment-methods',status_code=303)
        elif action=='remove-method':
            billing.remove_method(owner,fields.get('method',''),fields.get('confirmed')=='yes')
            return RedirectResponse(BASE+'/payment-methods',status_code=303)
        else:
            raise HTTPException(404,'Unknown billing action')
        # Never follow a provider-supplied URL to an arbitrary origin.
        if not billing._safe_url(result['url']):
            raise ValueError('Provider returned an untrusted redirect.')
        return RedirectResponse(result['url'],status_code=303)
    except HTTPException:
        raise
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else 'Stripe request failed. No paid access was granted. Retry safely or contact the operator.'
        return page('Billing action unavailable',f'<p>{e(message)}</p><a href="{BASE}">Return to billing</a>',session,status=400)


@router.get('/admin/billing')
def admin_page(request: Request):
    session=_session(request)
    if not session:
        return RedirectResponse('/billing/login',status_code=303)
    try:
        _admin(session,stepped=False)
    except ValueError:
        raise HTTPException(403,'Billing administrator role required') from None
    if time.time()-session['verified']>600:
        fields='<label>Your account password <input name="password" type="password" required autocomplete="current-password"></label>'
        return page('Verify administrator', '<p>Re-enter your individual Cortex password. Verification expires in ten minutes. Shared admin passwords are not accepted.</p>'+form(session,'/admin/billing/verify','Verify administrator',fields),session)
    accounts=billing.admin_accounts(session['owner'])
    summary=' · '.join(f'{label}: {sum(row["status"]==label for row in accounts)}' for label in ('active','trialing','past_due','canceled','unpaid'))
    body=f'<p class="notice">{len(accounts)} accounts · {e(summary)}</p><p>Platform-wide visibility. Stripe records open in the Stripe Dashboard and require Stripe authorization.</p><div class="table"><table><tr><th>Workspace</th><th>Plan / status</th><th>Renewal</th><th>Stripe</th><th>Action</th></tr>'
    for row in accounts:
        customer=row['customer'] or ''
        link=f'<a href="https://dashboard.stripe.com/{"" if os.getenv("STRIPE_SECRET_KEY", "").startswith(("sk_live_","rk_live_")) else "test/"}customers/{e(customer)}">Customer</a>' if customer else 'Not linked'
        fields=f'<input type="hidden" name="target" value="{e(row["id"])}"><label><input type="checkbox" name="confirmed" value="yes" required>Confirm cancellation at period end</label>'
        cancel=form(session,'/admin/billing/cancel','Schedule cancellation',fields) if row['subscription'] else ''
        body+=f'<tr><td>{e(row["email"])}</td><td>{e(row["plan"] or "free")} / {e(row["status"] or "not_subscribed")}</td><td>{_date(row["period_end"])}</td><td>{link}</td><td>{cancel}</td></tr>'
    body+='</table></div><h2>Plan configuration</h2><p>Limits apply immediately. Use Stripe recurring Price IDs; existing subscriptions retain their Stripe prices. Do not change price mappings for active subscriptions without a migration.</p>'
    for name,item in billing.plans().items():
        if name=='starter':
            continue
        fields=f'<input type="hidden" name="plan" value="{name}">'
        for key,label in [('monthly','Monthly price ID'),('annual','Annual price ID'),('files','File allowance'),('storage_mb','Storage MiB'),('ai_requests','Monthly custom AI requests')]:
            fields+=f'<label>{label}<input name="{key}" value="{e(item[key])}" {"type=number min=1 max=100000" if key not in {"monthly","annual"} else ""}></label>'
        fields+='<label><input type="checkbox" name="confirmed" value="yes" required>Confirm configuration change</label>'
        body+=f'<section><h3>{e(name.title())}</h3>'+form(session,'/admin/billing/plans','Save plan',fields)+'</section>'
    with store.connection() as db:
        events=db.execute("SELECT owner,action,target,created FROM events WHERE action LIKE 'billing_%' ORDER BY created DESC LIMIT 100").fetchall()
    body+='<h2>Latest 100 billing events</h2><div class="table"><table>'
    for event in events:
        body+='<tr>'+''.join('<td>'+e(v)+'</td>' for v in event)+'</tr>'
    return page('Billing administration',body+'</table></div>',session)


@router.post('/admin/billing/verify')
async def verify_admin(request: Request):
    session=_protected(request)
    fields=await _fields(request,session)
    try:
        _admin(session,stepped=False)
        with store.connection() as db:
            email=db.execute('SELECT email FROM users WHERE id=?',(session['owner'],)).fetchone()[0]
        store.login(email,fields.get('password',''))
        with store.connection() as db:
            db.execute('UPDATE billing_sessions SET verified=? WHERE digest=?',(time.time(),session['digest']))
        store.audit(session['owner'],'billing_admin_verified')
        return RedirectResponse('/admin/billing',status_code=303)
    except ValueError:
        raise HTTPException(403,'Administrator verification rejected') from None


@router.post('/admin/billing/{action}')
async def admin_action(action: str, request: Request):
    session=_protected(request)
    fields=await _fields(request,session)
    try:
        _admin(session)
        if fields.get('confirmed')!='yes':
            raise ValueError('Confirmation required.')
        if action=='cancel':
            billing.admin_cancel(session['owner'],fields.get('target',''),True)
        elif action=='plans':
            billing.configure_plan(session['owner'],fields.get('plan',''),fields.get('monthly',''),fields.get('annual',''),
                int(fields.get('files','0')),int(fields.get('storage_mb','0')),int(fields.get('ai_requests','0')))
        else:
            raise HTTPException(404,'Unknown admin action')
        return RedirectResponse('/admin/billing',status_code=303)
    except HTTPException:
        raise
    except Exception as exc:
        return page('Admin action rejected',f'<p>{e(str(exc) if isinstance(exc,ValueError) else "Provider unavailable; check configuration.")}</p>',session,status=403)
