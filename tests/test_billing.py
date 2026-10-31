"""Billing contract tests: real signature verification, isolated DB, mocked Stripe transport."""
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from cortex import billing, store
from cortex.api import app
from cortex.billing_routes import COOKIE, issue_session


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CORTEX_DB', str(tmp_path / 'billing.sqlite3'))
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_contract_not_a_real_key')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_contract_not_a_real_secret')
    monkeypatch.setenv('STRIPE_PRICE_PRO_MONTHLY','price_promonth')
    monkeypatch.setenv('STRIPE_PRICE_PRO_ANNUAL','price_proyear')
    monkeypatch.setenv('BILLING_BASE_URL','http://testserver')
    # HTTP allowed only on loopback in application; TestClient sets an explicit
    # localhost origin to exercise the identical cookie/CSRF behavior.
    monkeypatch.setenv('BILLING_BASE_URL','http://localhost:8503')
    monkeypatch.delenv('CORTEX_ADMIN_USER_ID',raising=False)
    store.initialize()
    return store.signup('billing@example.test','billing-test-password-123')['id']


def link(owner):
    with store.connection() as db:
        db.execute('INSERT INTO billing_accounts(owner,customer,updated) VALUES(?,?,?)',(owner,'cus_contract',time.time()))


def subscription(status='active', interval='month', end=None):
    return {'id':'sub_contract','customer':'cus_contract','created':1,'status':status,'cancel_at_period_end':False,
            'items':{'data':[{'current_period_start':time.time()-60,'current_period_end':end or time.time()+86400,
                             'price':{'id':'price_pro'+interval,'product':'prod_contract'}}]}}


def signed(event_id, kind, obj, live=False):
    raw=json.dumps({'id':event_id,'type':kind,'livemode':live,'data':{'object':obj}}).encode()
    timestamp=int(time.time())
    sig=hmac.new(b'whsec_contract_not_a_real_secret',str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return raw,f't={timestamp},v1={sig}'


def auth(owner):
    client=TestClient(app,base_url='http://localhost:8503')
    token=issue_session(owner)
    client.cookies.set(COOKIE,token)
    with store.connection() as db:
        csrf=db.execute('SELECT csrf FROM billing_sessions WHERE owner=? ORDER BY issued DESC',(owner,)).fetchone()[0]
    return client,csrf


def test_checkout_monthly_annual_reuses_pending_without_entitlements(workspace, monkeypatch):
    import stripe
    captured=[]
    monkeypatch.setattr(stripe.Customer,'create',lambda **kw:{'id':'cus_contract'})
    monkeypatch.setattr(stripe.checkout.Session,'create',lambda **kw: captured.append(kw) or {'id':'cs_contract','url':'https://checkout.stripe.com/test/contract','expires_at':time.time()+3600})
    monkeypatch.setattr(stripe.checkout.Session,'retrieve',lambda *a,**kw:{'status':'open'})
    first=billing.checkout(workspace,'pro','annual')
    assert billing.checkout(workspace,'pro','annual')==first
    assert len(captured)==1 and captured[0]['line_items'][0]['price']=='price_proyear'
    assert captured[0]['idempotency_key']
    assert billing.limits(workspace)['name']=='free'
    with pytest.raises(ValueError,match='unfinished'):
        billing.checkout(workspace,'pro','monthly')


@pytest.mark.parametrize('status,expected',[('active','pro'),('trialing','pro'),('past_due','free'),('unpaid','free'),('canceled','free'),('incomplete','free')])
def test_signed_webhook_lifecycle_and_replay(workspace,monkeypatch,status,expected):
    import stripe
    link(workspace)
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw:{'data':[subscription(status)],'has_more':False})
    raw,sig=signed('evt_status','customer.subscription.updated',{'customer':'cus_contract'})
    assert billing.webhook(raw,sig)['status']=='processed'
    assert billing.account(workspace)['status']==status
    assert billing.limits(workspace)['name']==expected
    assert billing.webhook(raw,sig)['status']=='duplicate'


def test_invoice_failure_renewal_and_reversed_events(workspace,monkeypatch):
    import stripe
    link(workspace)
    state={'status':'past_due'}
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw:{'data':[subscription(state['status'])],'has_more':False})
    invoice={'id':'in_contract','customer':'cus_contract','status':'open','currency':'eur','amount_due':500,'amount_paid':0,'created':1,'hosted_invoice_url':'https://invoice.stripe.com/i/test','invoice_pdf':'https://pay.stripe.com/invoice/test/pdf'}
    monkeypatch.setattr(stripe.Invoice,'retrieve',lambda *a,**kw:invoice)
    assert billing.webhook(*signed('evt_failed','invoice.payment_failed',{'id':'in_contract','customer':'cus_contract'}))['status']=='processed'
    assert billing.limits(workspace)['name']=='free'
    state['status']='active'; invoice.update(status='paid',amount_paid=500)
    billing.webhook(*signed('evt_paid','invoice.paid',{'id':'in_contract','customer':'cus_contract'}))
    assert billing.limits(workspace)['name']=='pro'
    # An older failed-event payload cannot roll back Stripe's latest state.
    billing.webhook(*signed('evt_old_failed','invoice.payment_failed',{'id':'in_contract','customer':'cus_contract'}))
    with store.connection() as db:
        assert db.execute('SELECT status FROM billing_invoices').fetchone()[0]=='paid'
    assert billing.limits(workspace)['name']=='pro'


def test_webhook_invalid_signature_mode_and_retry(workspace,monkeypatch):
    import stripe
    link(workspace)
    raw,sig=signed('evt_invalid','customer.subscription.updated',{'customer':'cus_contract'})
    with pytest.raises(ValueError,match='signature'):
        billing.webhook(raw,sig+'bad')
    with pytest.raises(ValueError,match='mode'):
        billing.webhook(*signed('evt_live','customer.subscription.updated',{'customer':'cus_contract'},True))
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw: (_ for _ in ()).throw(RuntimeError('transport error')))
    client=TestClient(app)
    assert client.post('/webhooks/stripe',content=raw,headers={'stripe-signature':sig}).status_code==503
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM billing_events').fetchone()[0]==0
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw:{'data':[subscription()],'has_more':False})
    assert client.post('/webhooks/stripe',content=raw,headers={'stripe-signature':sig}).status_code==200


def test_return_refresh_and_expiry_never_grant_unverified_access(workspace,monkeypatch):
    import stripe
    link(workspace)
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw:{'data':[subscription()],'has_more':False})
    client,csrf=auth(workspace)
    assert client.get('/workspace/settings/billing?checkout=returned').status_code==200
    assert billing.limits(workspace)['name']=='free'
    billing.refresh(workspace)
    assert billing.limits(workspace)['name']=='free'
    billing.webhook(*signed('evt_activate','customer.subscription.updated',{'customer':'cus_contract'}))
    assert billing.limits(workspace)['name']=='pro'
    with store.connection() as db:
        db.execute('UPDATE billing_accounts SET period_end=? WHERE owner=?',(time.time()-1,workspace))
    assert billing.limits(workspace)['name']=='free'


def test_methods_owner_binding_default_removal_and_hosted_add(workspace,monkeypatch):
    import stripe
    link(workspace)
    methods=[{'id':'pm_one','brand':'visa','last4':'4242','exp_month':12,'exp_year':2030,'is_default':1},
             {'id':'pm_two','brand':'mastercard','last4':'4444','exp_month':11,'exp_year':2031,'is_default':0}]
    monkeypatch.setattr(billing,'_methods',lambda cid:('pm_one',methods))
    changes=[]
    monkeypatch.setattr(stripe.Customer,'modify',lambda *a,**kw:changes.append((a,kw)))
    monkeypatch.setattr(stripe.PaymentMethod,'detach',lambda *a,**kw:changes.append((a,kw)))
    with pytest.raises(ValueError,match='belong'):
        billing.default_method(workspace,'pm_foreign')
    with pytest.raises(ValueError,match='another default'):
        billing.remove_method(workspace,'pm_one',True)
    billing.default_method(workspace,'pm_two')
    billing.remove_method(workspace,'pm_two',True)
    assert len(changes)==2
    portal=[]
    monkeypatch.setattr(stripe.billing_portal.Session,'create',lambda **kw:portal.append(kw) or {'url':'https://billing.stripe.com/p/test'})
    client,csrf=auth(workspace)
    response=client.post('/billing/actions/payment-methods',data={'csrf':csrf},follow_redirects=False)
    assert response.status_code==303
    assert portal[0]['customer']=='cus_contract' and portal[0]['flow_data']['type']=='payment_method_update'
    assert client.get('/workspace/settings/billing/payment-methods').status_code==200
    with store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM billing_methods WHERE owner=?',(workspace,)).fetchone()[0]==2


def test_invoice_customer_binding_pagination_and_download(workspace,monkeypatch):
    import stripe
    link(workspace)
    row={'id':'in_one','customer':'cus_contract','status':'paid','currency':'eur','amount_due':500,'amount_paid':500,'created':1,'invoice_pdf':'https://pay.stripe.com/invoice/a/pdf'}
    monkeypatch.setattr(stripe.Invoice,'list',lambda **kw:{'data':[row],'has_more':True})
    client,csrf=auth(workspace)
    response=client.get('/workspace/settings/billing/invoices')
    assert response.status_code==200 and 'Download PDF' in response.text and 'Next invoices' in response.text
    with pytest.raises(ValueError,match='cursor'):
        billing.invoices(workspace,'in_foreign')
    row['customer']='cus_foreign'
    with pytest.raises(ValueError,match='mismatch'):
        billing.invoices(workspace)


def test_auth_csrf_admin_stepup_and_password_revocation(workspace,monkeypatch):
    import stripe
    client,csrf=auth(workspace)
    assert TestClient(app).post('/billing/actions/portal',data={'csrf':csrf}).status_code==401
    assert client.post('/billing/actions/portal',data={'csrf':'wrong'}).status_code==403
    assert client.post('/billing/actions/portal',data={'csrf':csrf},headers={'origin':'https://evil.example'}).status_code==403
    assert client.get('/admin/billing').status_code==403
    assert client.post('/admin/billing/verify',data={'csrf':csrf,'password':'billing-test-password-123'}).status_code==403
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',workspace)
    assert 'Verify administrator' in client.get('/admin/billing').text
    assert client.post('/admin/billing/plans',data={'csrf':csrf,'confirmed':'yes'}).status_code==403
    assert client.post('/admin/billing/verify',data={'csrf':csrf,'password':'billing-test-password-123'},follow_redirects=False).status_code==303
    assert client.get('/admin/billing').status_code==200
    store.change_password(workspace,'billing-test-password-123','changed-billing-password-123')
    assert client.post('/billing/actions/portal',data={'csrf':csrf}).status_code==401


def test_local_login_and_logout(workspace):
    client=TestClient(app,base_url='http://localhost:8503')
    assert client.get('/billing/login').status_code==200
    csrf=client.cookies['cortex_login_csrf']
    assert client.post('/billing/login',data={'csrf':csrf,'email':'billing@example.test','password':'billing-test-password-123'},follow_redirects=False).status_code==303
    with store.connection() as db:
        csrf=db.execute('SELECT csrf FROM billing_sessions WHERE owner=?',(workspace,)).fetchone()[0]
    assert client.get('/workspace/settings/billing').status_code==200
    assert client.post('/billing/logout',data={'csrf':csrf},follow_redirects=False).status_code==303
    assert client.get('/workspace/settings/billing',follow_redirects=False).status_code==303


def test_ai_and_dataset_quotas_are_enforced_not_ui_only(workspace):
    from cortex import data
    with store.connection() as db:
        db.execute("UPDATE billing_plans SET ai_requests=1,files=1 WHERE name='free'")
    request=billing.reserve_request(workspace)
    billing.finish_request(workspace,request,failed=True)
    with pytest.raises(ValueError,match='allowance'):
        billing.reserve_request(workspace)
    data.ingest(workspace,'first.txt',b'First trusted internal document')
    with pytest.raises(ValueError,match='allowance'):
        data.ingest(workspace,'second.txt',b'Second trusted internal document')
    other=store.signup('other-billing@example.test','other-strong-password-123')['id']
    assert billing.usage(other)['ai_requests']==0


def test_admin_plan_configuration_and_confirmed_cancel(workspace,monkeypatch):
    import stripe
    link(workspace)
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',workspace)
    client,csrf=auth(workspace)
    client.post('/admin/billing/verify',data={'csrf':csrf,'password':'billing-test-password-123'})
    monkeypatch.setattr(stripe.Price,'retrieve',lambda price,**kw:{'active':True,'recurring':{'interval':'month' if price.endswith('month') else 'year','interval_count':1}})
    response=client.post('/admin/billing/plans',data={'csrf':csrf,'confirmed':'yes','plan':'pro','monthly':'price_promonth','annual':'price_proyear','files':'200','storage_mb':'900','ai_requests':'2000'},follow_redirects=False)
    assert response.status_code==303
    assert billing.plans()['pro']['files']==200
    with store.connection() as db:
        db.execute("UPDATE billing_accounts SET subscription='sub_contract' WHERE owner=?",(workspace,))
    monkeypatch.setattr(stripe.Subscription,'retrieve',lambda *a,**kw:subscription())
    changes=[]
    monkeypatch.setattr(stripe.Subscription,'modify',lambda *a,**kw:changes.append(kw))
    assert client.post('/admin/billing/cancel',data={'csrf':csrf,'target':workspace}).status_code==403
    assert client.post('/admin/billing/cancel',data={'csrf':csrf,'target':workspace,'confirmed':'yes'},follow_redirects=False).status_code==303
    assert changes[0]['cancel_at_period_end'] is True
    assert any(e['action']=='billing_admin_cancel_scheduled' for e in store.history(workspace,'events'))


def test_no_secrets_on_public_pages(workspace):
    response=TestClient(app).get('/pricing')
    assert response.status_code==200 and 'Pro' in response.text and 'Enterprise' in response.text
    assert response.headers['referrer-policy']=='same-origin'
    assert 'sk_test_contract' not in response.text and 'whsec_contract' not in response.text
    assert billing._safe_url('https://stripe.com.evil.example/no')==''
    assert billing._safe_url('javascript:alert(1)')==''


def test_upgrade_downgrade_annual_and_scheduled_cancellation(workspace,monkeypatch):
    import stripe
    link(workspace)
    monkeypatch.setenv('STRIPE_PRICE_TEAM_MONTHLY','price_teammonth')
    state={'sub':subscription(interval='year')}
    monkeypatch.setattr(stripe.Subscription,'list',lambda **kw:{'data':[state['sub']],'has_more':False})
    billing.webhook(*signed('evt_annual','customer.subscription.updated',{'customer':'cus_contract'}))
    assert billing.account(workspace)['interval']=='annual'
    state['sub']['items']['data'][0]['price']['id']='price_teammonth'
    billing.webhook(*signed('evt_upgrade','customer.subscription.updated',{'customer':'cus_contract'}))
    assert billing.limits(workspace)['name']=='team'
    state['sub']['items']['data'][0]['price']['id']='price_promonth'
    state['sub']['cancel_at_period_end']=True
    billing.webhook(*signed('evt_downgrade','customer.subscription.updated',{'customer':'cus_contract'}))
    assert billing.limits(workspace)['name']=='pro'
    assert billing.account(workspace)['cancel_at_period_end']==1
    state['sub']['status']='canceled'
    billing.webhook(*signed('evt_cancel','customer.subscription.deleted',{'customer':'cus_contract'}))
    assert billing.limits(workspace)['name']=='free'


def test_concurrent_quota_reservations_and_idempotent_schema(workspace):
    from concurrent.futures import ThreadPoolExecutor
    with store.connection() as db:
        db.execute("UPDATE billing_plans SET ai_requests=1 WHERE name='free'")
    def attempt(_):
        try:
            return billing.reserve_request(workspace)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(attempt,range(3)))
    assert sum(r is not None for r in results)==1
    store.initialize(); store.initialize()
    assert billing.usage(workspace)['ai_requests']==1


def test_expired_session_and_removed_admin_assignment(workspace,monkeypatch):
    client,csrf=auth(workspace)
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',workspace)
    client.post('/admin/billing/verify',data={'csrf':csrf,'password':'billing-test-password-123'})
    with store.connection() as db:
        db.execute('UPDATE billing_sessions SET verified=? WHERE owner=?',(time.time()-601,workspace))
    assert client.post('/admin/billing/plans',data={'csrf':csrf,'confirmed':'yes'}).status_code==403
    monkeypatch.delenv('CORTEX_ADMIN_USER_ID')
    assert client.get('/admin/billing').status_code==403
    with store.connection() as db:
        db.execute('UPDATE billing_sessions SET expires=0 WHERE owner=?',(workspace,))
    assert client.post('/billing/actions/portal',data={'csrf':csrf}).status_code==401


def test_completed_pending_checkout_prevents_second_payment(workspace,monkeypatch):
    import stripe
    link(workspace)
    with store.connection() as db:
        db.execute('INSERT INTO billing_checkouts VALUES(?,?,?,?,?,?)',(workspace,'pro','monthly','cs_done','https://checkout.stripe.com/test',time.time()+600))
    monkeypatch.setattr(stripe.checkout.Session,'retrieve',lambda *a,**kw:{'status':'complete'})
    with pytest.raises(ValueError,match='do not pay again'):
        billing.checkout(workspace,'pro')


def test_login_requires_csrf_cookie(workspace):
    client=TestClient(app)
    assert client.post('/billing/login',data={'csrf':'!invalid','email':'billing@example.test','password':'billing-test-password-123'}).status_code==403


def test_admin_can_disable_unpurchased_prices_and_saves_modern_payment_refs(workspace,monkeypatch):
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',workspace)
    billing.configure_plan(workspace,'pro','','',100,500,1000)
    assert billing.plans()['pro']['monthly']==''
    with pytest.raises(ValueError,match='price ID'):
        billing.checkout(workspace,'pro')
    with store.connection() as db:
        billing._save_invoice(db,workspace,{'id':'in_modern','payments':{'data':[{'id':'inpay_one','payment':{'type':'payment_intent','payment_intent':'pi_one'}}]}})
    with store.connection() as db:
        assert db.execute('SELECT payment FROM billing_invoices WHERE owner=?',(workspace,)).fetchone()[0]=='pi_one'
