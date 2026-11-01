"""Operator Stripe diagnostics and explicitly test-only portal setup."""
import hashlib
import json
import os
from collections import defaultdict
from cortex import billing,store


def diagnose():
    import stripe
    key=billing._key()
    report={'test_mode':key.startswith(('sk_test_','rk_test_')),'webhook_secret_configured':bool(os.getenv('STRIPE_WEBHOOK_SECRET')),'prices':[]}
    seen=set()
    for name,plan in billing.plans().items():
        for interval in ('monthly','annual'):
            pid=plan[interval]
            if not pid:
                continue
            item={'plan':name,'interval':interval,'duplicate_mapping':pid in seen}
            seen.add(pid)
            try:
                price=stripe.Price.retrieve(pid,api_key=key)
                recurrence=price.get('recurring') or {}
                item.update(active=bool(price.get('active')),currency=price.get('currency'),interval_matches=recurrence.get('interval')==('month' if interval=='monthly' else 'year') and recurrence.get('interval_count')==1)
            except Exception as exc:
                item['error']=type(exc).__name__
            report['prices'].append(item)
    configuration=os.getenv('STRIPE_PORTAL_CONFIGURATION')
    if configuration:
        configs=[stripe.billing_portal.Configuration.retrieve(configuration,api_key=key)]
    else:
        configs=stripe.billing_portal.Configuration.list(limit=100,api_key=key)['data']
        configs=[c for c in configs if c.get('is_default')]
    report['portal']={}
    if configs:
        config=configs[0];features=config.get('features',{})
        report['portal']={'active':bool(config.get('active')),'explicit_configuration':bool(configuration),
                          **{feature:bool(features.get(feature,{}).get('enabled')) for feature in ('payment_method_update','invoice_history','customer_update','subscription_update','subscription_cancel')}}
    with store.connection() as db:
        report['processed_webhooks']=db.execute('SELECT COUNT(*) FROM billing_events').fetchone()[0]
    report['notice']='A signing secret alone does not forward events. Keep stripe listen running locally, or configure a reachable HTTPS webhook destination in deployment.'
    return report


def configure_test_portal():
    import stripe
    key=billing._key()
    if not key.startswith(('sk_test_','rk_test_')):
        raise ValueError('Automated portal setup is limited to Stripe Test Mode.')
    products=defaultdict(list)
    configured=[]
    for name,plan in billing.plans().items():
        if name in {'free','starter'}:
            continue
        for interval in ('monthly','annual'):
            pid=plan[interval]
            if not pid:
                continue
            price=stripe.Price.retrieve(pid,api_key=key)
            recurring=price.get('recurring') or {}
            if not price.get('active') or price.get('livemode') or recurring.get('interval')!=('month' if interval=='monthly' else 'year') or recurring.get('interval_count')!=1:
                raise ValueError('Use active test recurring prices that match their configured interval.')
            product=price.get('product')
            if not isinstance(product,str):
                raise ValueError('Stripe returned an unexpected product reference.')
            products[product].append(pid);configured.append(pid)
    if not products:
        raise ValueError('Configure at least one recurring test price first.')
    features={'customer_update':{'enabled':True,'allowed_updates':['name','email','address','phone']},
              'invoice_history':{'enabled':True},'payment_method_update':{'enabled':True},
              'subscription_cancel':{'enabled':True,'mode':'at_period_end','proration_behavior':'none'},
              'subscription_update':{'enabled':True,'default_allowed_updates':['price'],'proration_behavior':'always_invoice',
                                     'products':[{'product':product,'prices':sorted(prices)} for product,prices in sorted(products.items())]}}
    # Create an application-specific configuration; never modify another app's default portal.
    fingerprint=hashlib.sha256(json.dumps([features,billing._base_url()],sort_keys=True).encode()).hexdigest()[:24]
    config=stripe.billing_portal.Configuration.create(features=features,business_profile={'headline':'Cortex test subscription management'},
        default_return_url=billing._base_url()+'/workspace/settings/billing',metadata={'application':'cortex','environment':'test'},
        api_key=key,idempotency_key='cortex-test-portal-'+fingerprint)
    return config['id']


def probe_test_webhook(timeout=20):
    """Emit a real, reversible test configuration event; never create a payment."""
    import secrets,time
    import stripe
    key=billing._key()
    if not key.startswith(('sk_test_','rk_test_')):
        raise ValueError('Webhook probes are limited to Stripe Test Mode.')
    config_id=os.getenv('STRIPE_PORTAL_CONFIGURATION')
    if not config_id:
        raise ValueError('Configure the Cortex test portal first.')
    config=stripe.billing_portal.Configuration.retrieve(config_id,api_key=key)
    if config.get('livemode') or config.get('metadata',{}).get('application')!='cortex':
        raise ValueError('The probe only modifies the Cortex-owned test portal metadata.')
    previous=config.get('metadata',{}).get('cortex_delivery_probe','')
    nonce=secrets.token_hex(12);started=int(time.time())
    stripe.billing_portal.Configuration.modify(config_id,metadata={'cortex_delivery_probe':nonce},api_key=key,idempotency_key='probe-'+nonce)
    try:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            events=stripe.Event.list(type='billing_portal.configuration.updated',created={'gte':started-1},limit=20,api_key=key)
            for event in events['data']:
                if event.get('data',{}).get('object',{}).get('metadata',{}).get('cortex_delivery_probe')!=nonce:
                    continue
                with store.connection() as db:
                    if db.execute('SELECT 1 FROM billing_events WHERE id=?',(event['id'],)).fetchone():
                        return {'real_stripe_event_received':True,'signature_verified_and_recorded':True,'payment_created':False}
            time.sleep(.5)
        raise ValueError('Stripe emitted the test event, but the local app did not acknowledge it. Check the listener, API port and signing secret.')
    finally:
        stripe.billing_portal.Configuration.modify(config_id,metadata={'cortex_delivery_probe':previous},api_key=key,idempotency_key='restore-probe-'+nonce)
