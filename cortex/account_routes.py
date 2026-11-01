"""Account/admin routes using the existing authenticated, CSRF-protected service."""
import json
import secrets
import time
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import RedirectResponse
from cortex import billing,identity,organizations,store
from cortex.billing_routes import _session,_protected,_fields,_cookie,issue_session,page,form,e,login_redirect

router=APIRouter()


def _error(exc,session=None):
    message=str(exc) if isinstance(exc,ValueError) else 'Operation unavailable. Check configuration; private details are withheld.'
    return page('Request rejected',f'<p class="notice">{e(message)}</p><a href="/account/profile">Return to My Profile</a>',session,status=400)


def _script_page(title,body,script,session=None):
    response=page(title,body,session)
    nonce=secrets.token_urlsafe(24)
    response.body=response.body.replace(b'</body>',f'<script nonce="{nonce}">{script}</script></body>'.encode())
    response.headers['content-length']=str(len(response.body))
    response.headers['Content-Security-Policy']+=f"; script-src 'nonce-{nonce}'"
    return response


def _public_csrf(response,token):
    response.set_cookie('cortex_account_csrf',token,httponly=True,secure=billing._base_url().startswith('https://'),samesite='strict',max_age=900)
    return response


@router.get('/auth/connect')
def connect_page():
    csrf=secrets.token_urlsafe(32)
    body=f'<p>Verifying your workspace sign-in…</p><form method="post" action="/auth/connect" id="connect"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="ticket" id="ticket"></form><noscript>JavaScript is required for the secure workspace handoff. You can also sign in at /billing/login.</noscript>'
    script="const p=new URLSearchParams(location.hash.slice(1));const ticket=p.get('ticket');history.replaceState(null,'',location.pathname);if(ticket){document.getElementById('ticket').value=ticket;document.getElementById('connect').submit();}"
    return _public_csrf(_script_page('Connect your workspace',body,script),csrf)


@router.post('/auth/connect')
async def connect(request:Request):
    csrf=request.cookies.get('cortex_account_csrf')
    if not csrf:
        raise HTTPException(403,'Open the sign-in link first')
    fields=await _fields(request,{'csrf':csrf})
    try:
        owner,destination,authenticated_at=identity.redeem_bridge(fields.get('ticket',''))
        return _cookie(RedirectResponse(destination,status_code=303),issue_session(owner,authenticated_at))
    except Exception as exc:
        return _error(exc)


@router.get('/auth/reset')
def reset_page():
    csrf=secrets.token_urlsafe(32)
    body=f'<form method="post"><input type="hidden" name="csrf" value="{csrf}"><label>Registered email <input type="email" name="email" required maxlength="254"></label><button>Send password reset link</button></form><p>A configured SMTP service is required. Responses do not reveal whether an account exists.</p>'
    return _public_csrf(page('Forgot password',body),csrf)


@router.post('/auth/reset')
async def request_reset(request:Request):
    csrf=request.cookies.get('cortex_account_csrf')
    if not csrf:
        raise HTTPException(403,'Open the reset page first')
    fields=await _fields(request,{'csrf':csrf})
    store.initialize()
    try:
        identity.request_email('reset',email=fields.get('email',''))
        return page('Reset requested','<p>If an eligible account exists, a reset link will be delivered. Check your inbox or contact the operator.</p>')
    except Exception as exc:
        return _error(exc)


@router.get('/auth/email')
def email_page():
    csrf=secrets.token_urlsafe(32)
    body=f'<p>Confirm the emailed verification request. For a password reset, enter a new password; for email verification leave it blank.</p><form method="post" id="verify"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="token" id="token"><label>New password (reset only)<input name="password" type="password" minlength="12" maxlength="256" autocomplete="new-password"></label><button>Confirm verified request</button></form>'
    script="document.getElementById('token').value=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);"
    return _public_csrf(_script_page('Verify email request',body,script),csrf)


@router.post('/auth/email')
async def confirm_email(request:Request):
    csrf=request.cookies.get('cortex_account_csrf')
    if not csrf:
        raise HTTPException(403,'Open the emailed link first')
    fields=await _fields(request,{'csrf':csrf})
    try:
        identity.consume_email(fields.get('token',''),fields.get('password') or None)
        response=page('Verified','<p>Your request was verified. Sign in again using your updated credentials.</p><a href="/billing/login">Sign in</a>')
        response.delete_cookie('cortex_billing_session')
        return response
    except Exception as exc:
        return _error(exc)


@router.get('/auth/invitation')
def invitation_page(request:Request):
    session=_session(request)
    if not session:
        # A sign-in in another tab preserves this fragment without sending it to the server.
        return page('Sign in to accept invitation','<p>Sign in with the invited email using the workspace, then reopen the invitation. You can <a href="/billing/login" target="_blank" rel="noopener">sign in in another tab</a> and refresh this page.</p>')
    body=form(session,'/auth/invitation','Accept organization invitation','<input type="hidden" name="token" id="token">')
    script="document.getElementById('token').value=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'',location.pathname);"
    return _script_page('Accept verified invitation',body,script,session)


@router.post('/auth/invitation')
async def accept_invitation(request:Request):
    session=_protected(request);fields=await _fields(request,session)
    try:
        organizations.accept(session['owner'],fields.get('token',''))
        return RedirectResponse('/organizations',status_code=303)
    except Exception as exc:
        return _error(exc,session)


@router.get('/account/profile')
def profile_page(request:Request):
    session=_session(request)
    if not session:
        return login_redirect(request.url.path)
    owner=session['owner'];item=identity.profile(owner);current=billing.account(owner);usage=billing.usage(owner)
    fields=''.join(f'<label>{label}<input name="{key}" value="{e(item[key])}" maxlength="120"></label>' for key,label in [('full_name','Full name'),('company','Company / organization name'),('job_title','Job title'),('country','Country'),('timezone','Timezone')])
    body=f'<section><p>Email: {e(item["email"])} · {"Verified" if item["email_verified"] else "Not verified"}</p><p>Immutable account ID: {e(owner)}</p><p>Created: {e(time.strftime("%d %b %Y %H:%M UTC",time.gmtime(item["created"])))}</p>'+form(session,'/account/profile','Save profile',fields)+'</section>'
    body+=f'<section><h2>Subscription</h2><p>{e(current["plan"])} · {e(current["status"])} · {e(current.get("interval") or "No billing cycle")}</p><p>AI requests: {usage["ai_requests"]} / {usage["limits"]["ai_requests"]} · Files: {usage["files"]} / {usage["limits"]["files"]} · Storage: {usage["storage_bytes"]/1048576:.2f} / {usage["limits"]["storage_mb"]} MiB</p><a href="/workspace/settings/billing">Manage subscription, payment methods and invoices</a></section>'
    return page('My Profile',body,session)


@router.post('/account/profile')
async def save_profile(request:Request):
    session=_protected(request);fields=await _fields(request,session)
    try:
        identity.save_profile(session['owner'],**{key:fields.get(key,'') for key in ('full_name','company','job_title','country','timezone')})
        return RedirectResponse('/account/profile',status_code=303)
    except Exception as exc:
        return _error(exc,session)


@router.get('/account/settings')
def settings_page(request:Request):
    session=_session(request)
    if not session:
        return login_redirect(request.url.path)
    body='<section><h2>Password</h2>'+form(session,'/account/settings/password','Change password','<label>Current password<input name="current" type="password" required></label><label>New password<input name="password" type="password" minlength="12" maxlength="256" required></label>')+'</section>'
    body+='<section><h2>Verified email change</h2><p>SMTP is required. No email changes before a single-use verification link is confirmed.</p>'+form(session,'/account/settings/email','Send verification','<label>New email<input name="email" type="email" required></label><label>Current password<input name="password" type="password" required></label>')+'</section>'
    body+=form(session,'/account/settings/revoke','Revoke other sessions','<label>Current password<input name="password" type="password" required></label>')
    body+='<section><h2>Delete account</h2><p>Private files and chat are erased. Financial audit records and shared organization data are retained. Transfer sole organization ownership and finish Stripe cancellation first.</p>'+form(session,'/account/settings/delete','Delete account','<label>Current password<input name="password" type="password" required></label><label>Type DELETE MY ACCOUNT<input name="confirmation" required></label>')+'</section>'
    return page('Account Settings',body,session)


@router.post('/account/settings/{action}')
async def account_action(action:str,request:Request):
    session=_protected(request);fields=await _fields(request,session);owner=session['owner']
    try:
        if action=='password':
            store.change_password(owner,fields.get('current',''),fields.get('password',''))
            return _cookie(RedirectResponse('/account/settings',status_code=303),issue_session(owner))
        if action=='email':
            identity.request_email('change',email=fields.get('email',''),owner=owner,password=fields.get('password',''))
            return page('Verification requested','<p>Check your new email address. Your address is unchanged until verification.</p>',session)
        if action=='revoke':
            proof=identity.step_up(owner,fields.get('password',''));identity.revoke_sessions(owner,proof)
            return _cookie(RedirectResponse('/account/settings',status_code=303),issue_session(owner))
        if action=='delete':
            identity.delete_account(owner,fields.get('password',''),fields.get('confirmation',''))
            response=RedirectResponse('/billing/login',status_code=303);response.delete_cookie('cortex_billing_session');return response
        raise HTTPException(404,'Unknown account action')
    except HTTPException:
        raise
    except Exception as exc:
        return _error(exc,session)


@router.get('/admin')
def admin_page(request:Request):
    session=_session(request)
    if not session:
        return login_redirect('/admin')
    try:
        identity.require_platform(session['owner'])
    except ValueError:
        raise HTTPException(403,'Platform administrator permission required') from None
    query=request.query_params.get('q','')
    try:
        proof=session.get('admin_proof','')
        try:
            identity.require_step(session['owner'],proof)
        except ValueError:
            return page('Verify administrator',form(session,'/admin/verify','Verify administrator','<label>Your account password<input name="password" type="password" required></label>'),session)
        result=identity.users(session['owner'],query,int(request.query_params.get('page','0')),proof=proof)
        body='<section><h2>Recent password verification</h2>'+form(session,'/admin/verify','Verify administrator','<label>Your account password<input name="password" type="password" required></label>')+'</section>'
        body+=f'<p>{result["total"]} matching registered users. Platform roles and organization roles are separate. No customer document contents or credentials appear here.</p><form method="get"><label>Search name/email<input name="q" value="{e(query)}" maxlength="120"></label><button>Search users</button></form><div class="table"><table><tr><th>Name / Email</th><th>ID</th><th>Role / status</th><th>Created / last sign-in (UTC)</th><th>Plan</th><th>Details</th></tr>'
        for user in result['data']:
            body+=f'<tr><td>{e(user["full_name"])}<br>{e(user["email"])}</td><td>{e(user["id"])}</td><td>{e(user["role"])} / {e(user["status"])}</td><td>{e(time.strftime('%d %b %Y %H:%M',time.gmtime(user['created'])))}<br>{e(time.strftime('%d %b %Y %H:%M',time.gmtime(user['last_login']))) if user['last_login'] else 'Never'}</td><td>{e(user["plan"])}</td><td><a href="/admin/users/{e(user["id"])}">View</a></td></tr>'
        body+='</table></div>'
        from urllib.parse import urlencode
        number=int(request.query_params.get('page','0'))
        if number:
            body+='<a href="?'+e(urlencode({'q':query,'page':number-1}))+'">Previous</a> '
        if (number+1)*25<result['total']:
            body+='<a href="?'+e(urlencode({'q':query,'page':number+1}))+'">Next</a>'
        import os
        if identity.platform_role(session['owner'])=='super_admin':
            body+='<p><a href="/admin/billing">Stripe billing administration</a></p>'
        return page('Admin Dashboard · User directory',body,session)
    except Exception as exc:
        return _error(exc,session)


@router.post('/admin/verify')
async def verify_admin(request:Request):
    session=_protected(request);fields=await _fields(request,session)
    try:
        identity.require_platform(session['owner'])
        proof=identity.step_up(session['owner'],fields.get('password',''))
        with store.connection() as db:
            db.execute('UPDATE billing_sessions SET admin_proof=?,verified=? WHERE digest=?',(proof,time.time(),session['digest']))
        return RedirectResponse('/admin',status_code=303)
    except ValueError:
        raise HTTPException(403,'Administrator verification rejected') from None


@router.get('/admin/users/{target}')
def user_page(target:str,request:Request):
    session=_protected(request)
    try:
        detail=identity.user_detail(session['owner'],target,session.get('admin_proof',''))
        body='<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(detail,indent=2))+'</pre>'
        if identity.platform_role(session['owner'])=='super_admin':
            body+='<p>Assign roles to individual registered accounts. Shared administrator credentials are not supported. Super Admin includes billing administration; ordinary customer tests need only Member.</p>'
            for action,choices,label in [('role',['member','admin','super_admin'],'Platform role'),('status',['active','suspended','deactivated'],'Account status'),('revoke',[],'Revoke sessions')]:
                fields=f'<input type="hidden" name="action" value="{action}">'
                if choices:
                    current=detail['user'].get('role' if action=='role' else 'status')
                    fields+='<label>'+label+'<select name="value">'+''.join('<option'+(' selected' if v==current else '')+'>'+v+'</option>' for v in choices)+'</select></label>'
                fields+='<label><input type="checkbox" name="confirmed" value="yes" required>Confirm action for this account</label>'
                body+=form(session,'/admin/users/'+target,'Apply '+label.lower(),fields)
        return page('User details',body,session)
    except ValueError:
        raise HTTPException(403,'User directory permission denied') from None


@router.post('/admin/users/{target}')
async def manage_user(target:str,request:Request):
    session=_protected(request);fields=await _fields(request,session)
    try:
        identity.require_platform(session['owner'],super_only=True)
    except ValueError:
        raise HTTPException(403,'Super Admin permission required') from None
    try:
        if fields.get('confirmed')!='yes':
            raise ValueError('Explicit confirmation required.')
        identity.manage_user(session['owner'],target,fields.get('action',''),fields.get('value',''),session.get('admin_proof',''))
        return RedirectResponse('/admin',status_code=303)
    except ValueError as exc:
        return _error(exc,session)


@router.get('/organizations')
def org_page(request:Request):
    session=_protected(request);items=organizations.list_for(session['owner'])
    body='<p>Create organizations, invite members, manage teams and use shared reports through Organization / Team Members in the main Cortex sidebar.</p>'
    for item in items:
        body+=f'<section><h2>{e(item["name"])}</h2><p>Your role: {e(item["role"])} · ID: {e(item["id"])}</p></section>'
    return page('Your organizations',body,session)
