"""Account profiles, permission checks and verified email workflows."""
import hashlib
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from cortex import store

PLATFORM_ROLES={'super_admin','admin'}
ORG_ROLES={'owner','manager','member','viewer'}
SAFE_DESTINATIONS={'/account/profile','/account/settings','/admin','/workspace/settings/billing','/workspace/settings/billing/payment-methods','/workspace/settings/billing/invoices','/workspace/settings/billing/usage','/admin/billing','/pricing','/organizations'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def active(owner, db=None):
    def check(conn):
        row=conn.execute('SELECT id,email,status,password_changed,sessions_revoked,email_verified FROM users WHERE id=?',(owner,)).fetchone()
        if not row or row['status']!='active':
            raise ValueError('Account is unavailable or inactive.')
        return dict(row)
    if db is not None:
        return check(db)
    with store.connection() as conn:
        return check(conn)


def platform_role(owner, db=None):
    def read(conn):
        active(owner,conn)
        primary=os.getenv('CORTEX_ADMIN_USER_ID','')
        # The configured immutable ID is authoritative, never an email.
        if owner==primary:
            return 'super_admin'
        row=conn.execute('SELECT role FROM platform_roles WHERE owner=?',(owner,)).fetchone()
        return row[0] if row else 'member'
    if db is not None:
        return read(db)
    with store.connection() as conn:
        return read(conn)


def require_platform(owner, super_only=False, db=None):
    role=platform_role(owner,db)
    if role not in ({'super_admin'} if super_only else PLATFORM_ROLES):
        raise ValueError('Platform administrator permission required.')


def step_up(owner,password):
    account=active(owner)
    authenticated=store.login(account['email'],password)
    if authenticated['id']!=owner:
        raise ValueError('Authentication identity changed. Sign in again.')
    token=secrets.token_urlsafe(32)
    now=time.time()
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current=active(owner,db)
        if authenticated['issued']<max(current['sessions_revoked'],current['password_changed']):
            raise ValueError('Authentication was revoked. Sign in again.')
        db.execute('DELETE FROM auth_steps WHERE expires<?',(now,))
        db.execute('INSERT INTO auth_steps VALUES(?,?,?,?)',(digest(token),owner,now,now+600))
    store.audit(owner,'account_step_up')
    return token


def require_step(owner,proof,db=None):
    def check(conn):
        user=active(owner,conn)
        row=conn.execute('SELECT issued,expires FROM auth_steps WHERE digest=? AND owner=?',(digest(proof or ''),owner)).fetchone()
        if not row or row['expires']<=time.time() or row['issued']<max(user['password_changed'],user['sessions_revoked']):
            raise ValueError('Recent password verification required (valid for ten minutes).')
    if db is not None:
        return check(db)
    with store.connection() as conn:
        return check(conn)


def profile(owner):
    active(owner)
    with store.connection() as db:
        row=db.execute('SELECT u.id,u.email,u.created,u.last_login,u.email_verified,u.status,p.full_name,p.company,p.job_title,p.country,p.timezone FROM users u LEFT JOIN profiles p ON p.owner=u.id WHERE u.id=?',(owner,)).fetchone()
    return {k:(v if v is not None else ('UTC' if k=='timezone' else '')) for k,v in dict(row).items()}


def save_profile(owner,full_name='',company='',job_title='',country='',timezone='UTC'):
    values=[str(v).strip() for v in (full_name,company,job_title,country,timezone)]
    if any(len(v)>120 or any(ord(c)<32 for c in v) for v in values):
        raise ValueError('Profile fields must use printable text up to 120 characters.')
    try:
        ZoneInfo(values[-1])
    except (ZoneInfoNotFoundError,ValueError):
        raise ValueError('Choose a valid IANA timezone, for example Europe/Berlin.') from None
    with store.connection() as db:
        active(owner,db)
        db.execute('INSERT INTO profiles VALUES(?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET full_name=excluded.full_name,company=excluded.company,job_title=excluded.job_title,country=excluded.country,timezone=excluded.timezone',[owner]+values)
    store.audit(owner,'profile_updated')


def revoke_sessions(owner,proof):
    with store.connection() as db:
        require_step(owner,proof,db)
        changed=time.time()
        db.execute('UPDATE users SET sessions_revoked=? WHERE id=?',(changed,owner))
        db.execute('DELETE FROM auth_bridges WHERE owner=?',(owner,))
    store.audit(owner,'sessions_revoked')
    return changed


def email_ready():
    return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_FROM'))


def deliver(address,subject,body):
    if not email_ready():
        raise ValueError('Email delivery is not configured. Ask the operator to configure SMTP.')
    host=os.environ['SMTP_HOST']
    mode=os.getenv('SMTP_SECURITY','starttls')
    if mode not in {'starttls','ssl','local'} or (mode=='local' and host not in {'localhost','127.0.0.1','::1'}):
        raise ValueError('SMTP must use TLS; local plaintext is allowed only on loopback.')
    msg=EmailMessage();msg['From']=os.environ['SMTP_FROM'];msg['To']=address;msg['Subject']=subject;msg.set_content(body)
    factory=smtplib.SMTP_SSL if mode=='ssl' else smtplib.SMTP
    options={'context':ssl.create_default_context()} if mode=='ssl' else {}
    with factory(host,int(os.getenv('SMTP_PORT','465' if mode=='ssl' else '587')),timeout=8,**options) as smtp:
        if mode=='starttls':
            smtp.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USERNAME'):
            smtp.login(os.environ['SMTP_USERNAME'],os.getenv('SMTP_PASSWORD',''))
        smtp.send_message(msg)


def _throttle(db,key):
    now=time.time()
    db.execute('DELETE FROM email_attempts WHERE created<?',(now-3600,))
    if db.execute('SELECT COUNT(*) FROM email_attempts WHERE digest=? AND created>?',(digest(key),now-900)).fetchone()[0]>=5:
        raise ValueError('Too many email requests. Try again in 15 minutes.')
    db.execute('INSERT INTO email_attempts VALUES(?,?)',(digest(key),now))


def request_email(purpose,email=None,owner=None,password=None):
    if purpose not in {'reset','change','verify'}:
        raise ValueError('Unsupported verification request.')
    if not email_ready():
        raise ValueError('Email delivery is not configured. Configure SMTP before using verified email actions.')
    if purpose!='reset':
        user=active(owner)
        if purpose=='change':
            store.login(user['email'],password or '')
        email=store._email(email if purpose=='change' else user['email'])
    else:
        email=store._email(email)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');_throttle(db,purpose+':'+email)
        if purpose=='reset':
            row=db.execute("SELECT id FROM users WHERE email=? AND status='active'",(email,)).fetchone()
            owner=row[0] if row else None
        elif purpose=='change' and db.execute('SELECT 1 FROM users WHERE email=? AND id<>?',(email,owner)).fetchone():
            raise ValueError('Email address cannot be used.')
        if not owner:
            return
        token=secrets.token_urlsafe(32);now=time.time()
        db.execute('DELETE FROM email_tokens WHERE owner=? AND purpose=?',(owner,purpose))
        db.execute('INSERT INTO email_tokens VALUES(?,?,?,?,?,?)',(digest(token),owner,purpose,email,now+900,now))
    from cortex.billing import _base_url
    link=_base_url()+'/auth/email#token='+token
    try:
        deliver(email,'Cortex: '+purpose+' verification',f'Use this single-use link within 15 minutes:\n{link}\nIgnore this message if you did not request it.')
    except Exception:
        with store.connection() as db:
            db.execute('DELETE FROM email_tokens WHERE digest=?',(digest(token),))
        store.audit(owner,'email_delivery_failed',detail={'purpose':purpose})
        if purpose!='reset':
            raise ValueError('Email delivery failed. Your email was not changed.') from None
    else:
        store.audit(owner,'email_verification_requested',detail={'purpose':purpose})


def consume_email(token,new_password=None):
    from argon2 import PasswordHasher
    if new_password is not None and not 12<=len(new_password)<=256:
        raise ValueError('Use a password with 12–256 characters.')
    password_hash=PasswordHasher().hash(new_password) if new_password is not None else None
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM email_tokens WHERE digest=?',(digest(token),)).fetchone()
        if not row or row['expires']<=time.time():
            raise ValueError('Verification link is invalid, expired or already used.')
        user=active(row['owner'],db);now=time.time()
        if row['purpose']=='reset':
            if not password_hash or user['email']!=row['email']:
                raise ValueError('A valid new password is required.')
            db.execute("UPDATE users SET argon2_hash=?,password_hash='argon2',password_changed=?,email_verified=? WHERE id=?",(password_hash,now,now,row['owner']))
        else:
            if row['purpose']=='verify' and user['email']!=row['email']:
                raise ValueError('The account email has changed. Request a new link.')
            if db.execute('SELECT 1 FROM users WHERE email=? AND id<>?',(row['email'],row['owner'])).fetchone():
                raise ValueError('Email address cannot be used.')
            db.execute('UPDATE users SET email=?,email_verified=?,sessions_revoked=? WHERE id=?',(row['email'],now,now,row['owner']))
        db.execute('DELETE FROM email_tokens WHERE owner=?',(row['owner'],))
        db.execute('DELETE FROM attempts WHERE email=?',(user['email'],))
        db.execute("INSERT INTO events(owner,action,target,detail,created) VALUES(?,'email_verified',?,'{}',?)",(row['owner'],row['purpose'],now))


def users(actor,query='',page=0,size=25,proof=None):
    require_platform(actor)
    require_step(actor,proof)
    if not 0<=int(page)<=100000 or not 1<=int(size)<=100 or len(query)>120:
        raise ValueError('Invalid directory query.')
    with store.connection() as db:
        where=" WHERE (u.email LIKE ? ESCAPE '\\' OR COALESCE(p.full_name,'') LIKE ? ESCAPE '\\')"
        pattern='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        fields="SELECT u.id,u.email,COALESCE(p.full_name,'') full_name,u.created,u.last_login,u.status,COALESCE(r.role,'member') role,COALESCE(b.plan,'free') plan,COALESCE(b.status,'not_subscribed') subscription_status FROM users u LEFT JOIN profiles p ON p.owner=u.id LEFT JOIN platform_roles r ON r.owner=u.id LEFT JOIN billing_accounts b ON b.owner=u.id"
        rows=[dict(r) for r in db.execute(fields+where+' ORDER BY u.created DESC,u.id LIMIT ? OFFSET ?',(pattern,pattern,size,page*size))]
        total=db.execute("SELECT COUNT(*) FROM users u LEFT JOIN profiles p ON p.owner=u.id"+where,(pattern,pattern)).fetchone()[0]
    for row in rows:
        if row['id']==os.getenv('CORTEX_ADMIN_USER_ID'):
            row['role']='super_admin'
    return {'data':rows,'total':total}


def user_detail(actor,target,proof=None):
    require_platform(actor)
    require_step(actor,proof)
    # Explicit allowlist: no password, session, credential or raw-content fields.
    with store.connection() as db:
        row=db.execute("SELECT u.id,u.email,u.status,u.created,u.last_login,u.email_verified,COALESCE(p.full_name,'') full_name,COALESCE(p.company,'') company,COALESCE(p.job_title,'') job_title,COALESCE(p.country,'') country,COALESCE(p.timezone,'UTC') timezone,COALESCE(r.role,'member') role FROM users u LEFT JOIN profiles p ON p.owner=u.id LEFT JOIN platform_roles r ON r.owner=u.id WHERE u.id=?",(target,)).fetchone()
        if not row:
            raise ValueError('User not found.')
        memberships=[dict(r) for r in db.execute('SELECT m.organization,o.name,m.role FROM memberships m JOIN organizations o ON o.id=m.organization WHERE m.owner=?',(target,))]
        events=[dict(r) for r in db.execute('SELECT action,target,detail,created FROM events WHERE owner=? OR target=? ORDER BY created DESC LIMIT 100',(target,target))]
        plan=db.execute('SELECT plan,status,interval,period_end,customer,subscription FROM billing_accounts WHERE owner=?',(target,)).fetchone()
    return {'user':dict(row),'organizations':memberships,'activity':events,'billing':dict(plan) if plan else {'plan':'free','status':'not_subscribed'}}


def manage_user(actor,target,action,value,proof):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');require_platform(actor,True,db);require_step(actor,proof,db)
        row=db.execute('SELECT status FROM users WHERE id=?',(target,)).fetchone()
        if not row or row['status']=='deleted':
            raise ValueError('User is unavailable.')
        if action not in {'role','status','revoke'}:
            raise ValueError('Unsupported user action.')
        role=platform_role(target,db) if row['status']=='active' else (db.execute('SELECT role FROM platform_roles WHERE owner=?',(target,)).fetchone() or ['member'])[0]
        protected=target==os.getenv('CORTEX_ADMIN_USER_ID') or (role=='super_admin' and row['status']=='active' and db.execute("SELECT COUNT(*) FROM platform_roles r JOIN users u ON u.id=r.owner WHERE r.role='super_admin' AND u.status='active'").fetchone()[0]<=1)
        if protected and (action=='role' and value!='super_admin' or action=='status' and value!='active'):
            raise ValueError('The primary or last active Super Admin cannot be removed, demoted or disabled.')
        if action=='revoke':
            value=''
        if action=='role':
            if value not in {'super_admin','admin','member'}:
                raise ValueError('Organization roles must be assigned within an organization.')
            db.execute('DELETE FROM platform_roles WHERE owner=?',(target,))
            if value!='member':
                db.execute('INSERT INTO platform_roles VALUES(?,?)',(target,value))
        elif action=='status':
            if value not in {'active','suspended','deactivated'}:
                raise ValueError('Invalid account status.')
            db.execute('UPDATE users SET status=? WHERE id=?',(value,target))
        db.execute('UPDATE users SET sessions_revoked=? WHERE id=?',(time.time(),target))
        db.execute('INSERT INTO events(owner,action,target,detail,created) VALUES(?,?,?,?,?)',(actor,'admin_user_'+action,target,json.dumps({'value':value}),time.time()))


def issue_bridge(owner,destination='/account/profile'):
    if destination not in SAFE_DESTINATIONS:
        raise ValueError('Unsupported destination.')
    active(owner)
    token=secrets.token_urlsafe(32);now=time.time()
    with store.connection() as db:
        db.execute('DELETE FROM auth_bridges WHERE expires<?',(now,))
        db.execute('INSERT INTO auth_bridges VALUES(?,?,?,?,?)',(digest(token),owner,destination,now,now+60))
    from cortex.billing import _base_url
    return _base_url()+'/auth/connect#ticket='+token


def redeem_bridge(token):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM auth_bridges WHERE digest=?',(digest(token),)).fetchone()
        if not row or row['expires']<=time.time():
            raise ValueError('Sign-in link expired or was already used. Return to the workspace for a fresh link.')
        user=active(row['owner'],db)
        if row['issued']<max(user['sessions_revoked'],user['password_changed']):
            raise ValueError('Sign-in link has been revoked.')
        db.execute('DELETE FROM auth_bridges WHERE digest=?',(digest(token),))
        return row['owner'],row['destination'],row['issued']


def delete_account(owner,password,confirmation):
    user=active(owner)
    if confirmation!='DELETE MY ACCOUNT':
        raise ValueError('Type DELETE MY ACCOUNT to confirm.')
    store.login(user['email'],password)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if platform_role(owner,db)=='super_admin':
            raise ValueError('Transfer/remove administrator privileges before deleting this account.')
        for org in db.execute("SELECT organization FROM memberships WHERE owner=? AND role='owner'",(owner,)):
            if db.execute("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id=m.owner WHERE organization=? AND role='owner' AND u.status='active'",(org[0],)).fetchone()[0]<=1:
                raise ValueError('Transfer organization ownership or delete the organization first.')
        if db.execute('SELECT 1 FROM billing_checkouts WHERE owner=? AND expires>?',(owner,time.time())).fetchone():
            raise ValueError('Let the pending checkout expire before deleting this account.')
        bill=db.execute('SELECT subscription,status FROM billing_accounts WHERE owner=?',(owner,)).fetchone()
        if bill and bill['subscription'] and bill['status'] not in {'canceled','incomplete_expired'}:
            raise ValueError('End the Stripe subscription before deleting your account. Scheduled cancellation must finish first.')
        db.execute('DELETE FROM datasets WHERE owner=? AND id NOT IN (SELECT dataset FROM organization_datasets)',(owner,))
        for table in ('profiles','preferences','messages','feedback','runs','migrations','logistics_links','billing_methods','auth_steps','email_tokens','auth_bridges','billing_sessions','platform_roles','memberships','invitations'):
            column='inviter' if table=='invitations' else 'owner'
            db.execute(f'DELETE FROM {table} WHERE {column}=?',(owner,))
        db.execute('DELETE FROM attempts WHERE email=?',(user['email'],))
        db.execute('DELETE FROM invitations WHERE email=?',(user['email'],))
        db.execute("UPDATE users SET email=?,salt='',password_hash='',argon2_hash='',status='deleted',sessions_revoked=?,email_verified=0 WHERE id=?",('deleted-'+secrets.token_hex(16)+'@deleted.invalid',time.time(),owner))
        db.execute("INSERT INTO events(owner,action,target,detail,created) VALUES(?,'account_deleted',?,'{}',?)",(owner,owner,time.time()))
