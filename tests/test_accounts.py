"""Authentication, account lifecycle and tenant boundary regressions."""
import hashlib
import re
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from cortex import billing,identity,organizations,store
from cortex.api import app
from cortex.billing_routes import COOKIE,issue_session
from cortex.retrieval import build_index,search

PASSWORD='verified-test-password-123'


@pytest.fixture
def accounts(tmp_path,monkeypatch):
    monkeypatch.setenv('CORTEX_DB',str(tmp_path/'accounts.sqlite3'))
    monkeypatch.delenv('CORTEX_ADMIN_USER_ID',raising=False)
    monkeypatch.setenv('BILLING_BASE_URL','http://localhost:8503')
    monkeypatch.setenv('SMTP_HOST','localhost');monkeypatch.setenv('SMTP_FROM','cortex@example.test')
    store.initialize()
    a=store.signup('owner@example.test',PASSWORD)['id']
    b=store.signup('member@example.test',PASSWORD)['id']
    c=store.signup('outsider@example.test',PASSWORD)['id']
    return a,b,c


def logged(owner):
    client=TestClient(app,base_url='http://localhost:8503')
    client.cookies.set(COOKIE,issue_session(owner))
    with store.connection() as db:
        csrf=db.execute('SELECT csrf FROM billing_sessions WHERE owner=? ORDER BY issued DESC',(owner,)).fetchone()[0]
    return client,csrf


def smtp(monkeypatch):
    sent=[]
    monkeypatch.setattr(identity,'deliver',lambda to,subject,body:sent.append((to,subject,body)))
    return sent


def token(sent):
    return re.search(r'#token=([^\s]+)',sent[-1][2]).group(1)


def member(accounts,monkeypatch,role='member'):
    a,b,c=accounts
    oid=organizations.create(a,'Company One')
    sent=smtp(monkeypatch)
    organizations.invite(a,oid,'member@example.test',role)
    invitation=token(sent)
    organizations.accept(b,invitation)
    return oid


def test_legacy_migration_and_password_upgrade(accounts,monkeypatch):
    a,b,c=accounts
    salt=secrets.token_hex(16);legacy=store._hash(PASSWORD,salt)
    with store.connection() as db:
        db.execute("UPDATE users SET salt=?,password_hash=?,argon2_hash='' WHERE id=?",(salt,legacy,a))
    store.initialize();store.initialize()
    with store.connection() as db:
        assert db.execute('SELECT password_hash FROM users WHERE id=?',(a,)).fetchone()[0]==legacy
    user=store.login('owner@example.test',PASSWORD)
    assert user['id']==a and store.session_valid(user)
    with store.connection() as db:
        row=db.execute('SELECT argon2_hash,last_login FROM users WHERE id=?',(a,)).fetchone()
        assert row['argon2_hash'].startswith('$argon2id$') and row['last_login']>0
    assert store.login('owner@example.test',PASSWORD)['id']==a


def test_profile_whitelist_and_persistence(accounts):
    a,b,c=accounts
    identity.save_profile(a,'Full Name','My Company','Analyst','Germany','Europe/Berlin')
    assert identity.profile(a)['full_name']=='Full Name'
    assert identity.profile(b)['full_name']==''
    with pytest.raises(ValueError,match='timezone'):
        identity.save_profile(a,timezone='made/up')
    with pytest.raises(TypeError):
        identity.save_profile(a,role='super_admin')
    assert identity.profile(a)['email']=='owner@example.test'
    client,csrf=logged(a)
    assert client.post('/account/profile',data={'csrf':csrf,'full_name':'New Name','timezone':'UTC','owner':b},follow_redirects=False).status_code==303
    assert identity.profile(a)['full_name']=='New Name' and identity.profile(b)['full_name']==''
    assert client.post('/account/profile',data={'csrf':'bad'}).status_code==403


def test_primary_bootstrap_and_directory_never_exposes_credentials(accounts,monkeypatch):
    a,b,c=accounts
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID','owner@example.test')
    store.initialize()
    assert identity.platform_role(a)=='member'
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',a)
    store.initialize();store.initialize()
    assert identity.platform_role(a)=='super_admin'
    proof=identity.step_up(a,PASSWORD)
    result=identity.users(a,proof=proof)
    assert result['total']==3
    assert not any('password' in k or 'salt' in k for row in result['data'] for k in row)
    assert identity.users(a,'member@',proof=proof)['data'][0]['id']==b
    assert identity.users(a,'%',proof=proof)['total']==0
    with pytest.raises(ValueError):
        identity.users(b,proof=identity.step_up(b,PASSWORD))
    with pytest.raises(ValueError,match='verification'):
        identity.users(a)


def test_roles_protection_and_suspension_invalidates_both_sessions(accounts,monkeypatch):
    a,b,c=accounts;monkeypatch.setenv('CORTEX_ADMIN_USER_ID',a);store.initialize()
    proof=identity.step_up(a,PASSWORD)
    identity.manage_user(a,b,'role','admin',proof)
    assert identity.platform_role(b)=='admin'
    with pytest.raises(ValueError,match='administrator'):
        identity.manage_user(b,c,'role','super_admin',identity.step_up(b,PASSWORD))
    with pytest.raises(ValueError,match='primary'):
        identity.manage_user(a,a,'role','member',proof)
    user=store.login('member@example.test',PASSWORD);client,csrf=logged(b)
    identity.manage_user(a,b,'status','suspended',proof)
    assert not store.session_valid(user)
    assert client.post('/billing/actions/portal',data={'csrf':csrf}).status_code==401
    with pytest.raises(ValueError):
        store.login('member@example.test',PASSWORD)
    identity.manage_user(a,b,'status','active',proof)
    identity.manage_user(a,b,'role','member',proof)
    assert identity.platform_role(b)=='member'
    assert any(e['action']=='admin_user_role' and e['target']==b for e in store.history(a,'events'))


def test_last_super_admin_and_expired_step_protection(accounts,monkeypatch):
    a,b,c=accounts;monkeypatch.setenv('CORTEX_ADMIN_USER_ID',a);store.initialize()
    proof=identity.step_up(a,PASSWORD);monkeypatch.delenv('CORTEX_ADMIN_USER_ID')
    with pytest.raises(ValueError,match='last active'):
        identity.manage_user(a,a,'status','deactivated',proof)
    with store.connection() as db:
        db.execute('UPDATE auth_steps SET expires=0')
    with pytest.raises(ValueError,match='verification'):
        identity.manage_user(a,b,'role','admin',proof)


def test_verified_password_reset_email_change_and_replay(accounts,monkeypatch):
    a,b,c=accounts;sent=smtp(monkeypatch)
    user=store.login('owner@example.test',PASSWORD);client,csrf=logged(a)
    identity.request_email('reset','owner@example.test')
    reset=token(sent)
    with store.connection() as db:
        assert db.execute('SELECT digest FROM email_tokens').fetchone()[0]!=reset
    identity.consume_email(reset,'changed-password-123')
    assert not store.session_valid(user)
    assert client.post('/billing/actions/portal',data={'csrf':csrf}).status_code==401
    assert store.login('owner@example.test','changed-password-123')['id']==a
    with pytest.raises(ValueError,match='used'):
        identity.consume_email(reset,'another-password-123')
    identity.request_email('change','new-owner@example.test',a,'changed-password-123')
    assert identity.profile(a)['email']=='owner@example.test'
    identity.consume_email(token(sent))
    assert identity.profile(a)['email']=='new-owner@example.test'
    assert store.login('new-owner@example.test','changed-password-123')['id']==a
    with pytest.raises(ValueError):
        store.login('owner@example.test','changed-password-123')


def test_missing_delivery_expiry_throttle_and_unknown_recovery(accounts,monkeypatch):
    a,b,c=accounts;sent=smtp(monkeypatch)
    identity.request_email('reset','unknown@example.test')
    assert not sent
    identity.request_email('verify',owner=a)
    code=token(sent)
    with store.connection() as db:
        db.execute('UPDATE email_tokens SET expires=0')
    with pytest.raises(ValueError,match='expired'):
        identity.consume_email(code)
    for _ in range(4):
        identity.request_email('verify',owner=a)
    with pytest.raises(ValueError,match='Too many'):
        identity.request_email('verify',owner=a)
    monkeypatch.delenv('SMTP_HOST')
    with pytest.raises(ValueError,match='not configured'):
        identity.request_email('reset','owner@example.test')


def test_bridge_one_use_identity_mapping_expiry_and_revocation(accounts):
    a,b,c=accounts
    url=identity.issue_bridge(a,'/workspace/settings/billing');ticket=url.split('#ticket=')[1]
    client=TestClient(app,base_url='http://localhost:8503')
    client.get('/auth/connect');csrf=client.cookies['cortex_account_csrf']
    response=client.post('/auth/connect',data={'csrf':csrf,'ticket':ticket},follow_redirects=False)
    assert response.status_code==303 and response.headers['location']=='/workspace/settings/billing'
    assert 'owner@example.test' in client.get('/account/profile').text
    with pytest.raises(ValueError,match='already used'):
        identity.redeem_bridge(ticket)
    ticket=identity.issue_bridge(a).split('#ticket=')[1]
    identity.revoke_sessions(a,identity.step_up(a,PASSWORD))
    with pytest.raises(ValueError):
        identity.redeem_bridge(ticket)
    with pytest.raises(ValueError):
        identity.issue_bridge(a,'https://evil.example')
    ticket=identity.issue_bridge(b).split('#ticket=')[1]
    with store.connection() as db:
        db.execute('UPDATE auth_bridges SET expires=0')
    with pytest.raises(ValueError,match='expired'):
        identity.redeem_bridge(ticket)


def test_bridge_cannot_cross_password_revocation_race(accounts):
    a,b,c=accounts
    owner,destination,authenticated=identity.redeem_bridge(identity.issue_bridge(a).split('#ticket=')[1])
    identity.revoke_sessions(a,identity.step_up(a,PASSWORD))
    with pytest.raises(ValueError,match='revoked'):
        issue_session(owner,authenticated)


def test_verified_invites_ownership_roles_and_cross_org_teams(accounts,monkeypatch):
    a,b,c=accounts;sent=smtp(monkeypatch);oid=organizations.create(a,'One');other=organizations.create(c,'Other')
    organizations.invite(a,oid,'member@example.test','viewer');invitation=token(sent)
    with pytest.raises(ValueError,match='belongs'):
        organizations.accept(c,invitation)
    organizations.accept(b,invitation)
    assert identity.profile(b)['email_verified']
    with pytest.raises(ValueError):
        organizations.accept(b,invitation)
    with pytest.raises(ValueError):
        organizations.invite(b,oid,'outsider@example.test')
    team=organizations.save_team(a,oid,'Operations',[a,b])
    with pytest.raises(ValueError):
        organizations.save_team(c,other,'Hijack',[c],team)
    with pytest.raises(ValueError):
        organizations.save_team(a,oid,'Bad team',[c])
    proof=identity.step_up(a,PASSWORD)
    organizations.change_member(a,oid,b,'member',proof)
    assert b in organizations.teams(a,oid)[0]['members']
    organizations.change_member(a,oid,b,'remove',proof)
    assert b not in organizations.teams(a,oid)[0]['members']
    with pytest.raises(ValueError,match='last active'):
        organizations.change_member(a,oid,a,'viewer',proof)


def test_org_data_indexes_chats_and_billing_stay_isolated(accounts,monkeypatch):
    from cortex import data
    from cortex.agents import run_agents
    a,b,c=accounts;oid=member(accounts,monkeypatch)
    did=data.ingest(a,'policy.txt',b'Private organization shipment policy: dispatch requires confirmed capacity.')
    private=data.ingest(c,'other.txt',b'Other organization secret protocol.')
    organizations.share_dataset(a,oid,did,True)
    assert not store.datasets(a) and len(store.datasets(b,oid))==1
    with pytest.raises(ValueError):
        store.dataset(a,did)
    with pytest.raises(ValueError):
        store.dataset(c,did,oid)
    with pytest.raises(ValueError):
        data.ingest(a,'again.txt',b'Private organization shipment policy: dispatch requires confirmed capacity.')
    build_index(b,did,'bm25',oid)
    assert search(b,'dispatch capacity',organization=oid)
    assert not search(a,'dispatch capacity') and not search(c,'dispatch capacity')
    result=run_agents(b,'dispatch capacity',dataset_id=did,organization=oid)
    assert result['hits'] and not store.history(b,'messages')
    assert store.history(b,'messages',organization=oid)
    assert billing.account(b)['plan']=='free'
    with pytest.raises(ValueError):
        store.dataset(b,private,oid)
    organizations.change_member(a,oid,b,'remove',identity.step_up(a,PASSWORD))
    for fn in [lambda:search(b,'dispatch',organization=oid),lambda:store.dataset(b,did,oid),lambda:store.history(b,'messages',organization=oid)]:
        with pytest.raises(ValueError):
            fn()


def test_viewer_read_only_and_private_erasure_preserves_shared_assets(accounts,monkeypatch):
    from cortex import data
    a,b,c=accounts;oid=member(accounts,monkeypatch,'viewer')
    did=data.ingest(a,'shared.txt',b'Organization records retained for team.')
    organizations.share_dataset(a,oid,did,True)
    assert store.dataset(b,did,oid)['id']==did
    for fn in [lambda:build_index(b,did,'bm25',oid),lambda:store.delete_dataset(b,did,oid),lambda:organizations.share_dataset(b,oid,did,True)]:
        with pytest.raises(ValueError):
            fn()
    store.erase_workspace(a)
    assert store.dataset(b,did,oid)['id']==did
    proof=identity.step_up(a,PASSWORD)
    with pytest.raises(ValueError,match='shared datasets'):
        organizations.delete_organization(a,oid,proof,True)
    store.delete_dataset(a,did,oid);organizations.delete_organization(a,oid,proof,True)
    assert not organizations.list_for(a)


def test_account_deletion_and_subscription_retention_guards(accounts):
    from cortex import data
    a,b,c=accounts;data.ingest(b,'private.txt',b'Erase me permanently.')
    client,csrf=logged(b)
    identity.delete_account(b,PASSWORD,'DELETE MY ACCOUNT')
    assert client.post('/billing/actions/portal',data={'csrf':csrf}).status_code==401
    with store.connection() as db:
        row=db.execute('SELECT * FROM users WHERE id=?',(b,)).fetchone()
        assert row['status']=='deleted' and row['email'].endswith('@deleted.invalid') and not row['argon2_hash']
        assert db.execute('SELECT COUNT(*) FROM datasets WHERE owner=?',(b,)).fetchone()[0]==0
    with pytest.raises(ValueError):
        store.login('member@example.test',PASSWORD)
    oid=organizations.create(a,'Sole owner')
    with pytest.raises(ValueError,match='ownership'):
        identity.delete_account(a,PASSWORD,'DELETE MY ACCOUNT')
    with store.connection() as db:
        db.execute("INSERT INTO billing_accounts(owner,customer,subscription,status,updated) VALUES(?,?,'sub_test','active',?)",(c,'cus_test',time.time()))
    with pytest.raises(ValueError,match='subscription'):
        identity.delete_account(c,PASSWORD,'DELETE MY ACCOUNT')


def test_admin_http_stepup_and_unauthorized_csrf(accounts,monkeypatch):
    a,b,c=accounts;monkeypatch.setenv('CORTEX_ADMIN_USER_ID',a);store.initialize()
    regular,rcsrf=logged(b)
    assert regular.get('/admin').status_code==403
    assert regular.get('/admin/users/'+a).status_code==403
    client,csrf=logged(a)
    assert 'Verify administrator' in client.get('/admin').text
    assert client.post('/admin/verify',data={'csrf':'bad','password':PASSWORD}).status_code==403
    assert client.post('/admin/verify',data={'csrf':csrf,'password':PASSWORD},follow_redirects=False).status_code==303
    assert 'member@example.test' in client.get('/admin').text
    response=client.post('/admin/users/'+b,data={'csrf':csrf,'action':'role','value':'admin','confirmed':'yes'},follow_redirects=False)
    assert response.status_code==303 and identity.platform_role(b)=='admin'
    assert 'argon2_hash' not in client.get('/admin/users/'+b).text
    scoped,scoped_csrf=logged(b)
    assert scoped.post('/admin/verify',data={'csrf':scoped_csrf,'password':PASSWORD},follow_redirects=False).status_code==303
    directory=scoped.get('/admin')
    assert directory.status_code==200 and 'href="/admin/billing"' not in directory.text
    assert scoped.post('/admin/users/'+c,data={'csrf':scoped_csrf,'action':'role','value':'super_admin','confirmed':'yes'}).status_code==403
    assert identity.platform_role(c)=='member'


def test_email_http_roundtrip_and_form_origin_protection(accounts,monkeypatch):
    a,b,c=accounts;sent=smtp(monkeypatch)
    client=TestClient(app,base_url='http://localhost:8503')
    client.get('/auth/reset');csrf=client.cookies['cortex_account_csrf']
    assert client.post('/auth/reset',data={'csrf':csrf,'email':'owner@example.test'}).status_code==200
    code=token(sent);client.get('/auth/email');csrf=client.cookies['cortex_account_csrf']
    assert client.post('/auth/email',data={'csrf':csrf,'token':code,'password':'verified-new-password-123'},headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/auth/email',data={'csrf':csrf,'token':code,'password':'verified-new-password-123'}).status_code==200
    assert store.login('owner@example.test','verified-new-password-123')['id']==a


def test_password_change_revokes_pending_email_tokens_and_account_delete_blocks_checkout(accounts,monkeypatch):
    a,b,c=accounts;sent=smtp(monkeypatch)
    identity.request_email('reset','owner@example.test');code=token(sent)
    store.change_password(a,PASSWORD,'changed-account-password-123')
    with pytest.raises(ValueError,match='invalid'):
        identity.consume_email(code,'a-different-password-123')
    with store.connection() as db:
        db.execute('INSERT INTO billing_checkouts VALUES(?,?,?,?,?,?)',(b,'pro','monthly','cs_pending','https://checkout.stripe.com/test',time.time()+600))
    with pytest.raises(ValueError,match='checkout'):
        identity.delete_account(b,PASSWORD,'DELETE MY ACCOUNT')


def test_smtp_tls_verification_and_loopback_only_plaintext(accounts,monkeypatch):
    calls=[]
    class SMTP:
        def __init__(self,*args,**kwargs): calls.append(('connect',kwargs))
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def starttls(self,**kwargs): calls.append(('tls',kwargs))
        def login(self,*args): calls.append(('login',None))
        def send_message(self,message): calls.append(('send',message['To']))
    monkeypatch.setattr(identity.smtplib,'SMTP',SMTP)
    monkeypatch.setattr(identity.smtplib,'SMTP_SSL',SMTP)
    monkeypatch.setenv('SMTP_SECURITY','ssl')
    identity.deliver('owner@example.test','Verify','Secret token stays in this mocked transport.')
    import ssl
    assert calls[0][1]['context'].verify_mode==ssl.CERT_REQUIRED
    calls.clear();monkeypatch.setenv('SMTP_SECURITY','starttls')
    identity.deliver('owner@example.test','Verify','Body')
    assert any(name=='tls' and kwargs['context'].verify_mode==ssl.CERT_REQUIRED for name,kwargs in calls if name=='tls')
    monkeypatch.setenv('SMTP_SECURITY','local');monkeypatch.setenv('SMTP_HOST','outside.example')
    with pytest.raises(ValueError,match='TLS'):
        identity.deliver('owner@example.test','Verify','Body')


def test_step_up_cannot_outlive_a_concurrent_revocation(accounts,monkeypatch):
    a,b,c=accounts
    original=store.login
    def concurrent(email,password):
        result=original(email,password)
        with store.connection() as db:
            db.execute('UPDATE users SET sessions_revoked=? WHERE id=?',(time.time(),a))
        return result
    monkeypatch.setattr(store,'login',concurrent)
    with pytest.raises(ValueError,match='revoked'):
        identity.step_up(a,PASSWORD)
