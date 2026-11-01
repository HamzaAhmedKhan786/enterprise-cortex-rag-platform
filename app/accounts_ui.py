"""Native account, administrator and organization UI for the existing workspace."""
import os
import time
import pandas as pd
import streamlit as st
from cortex import billing, identity, organizations, store


def attempt(fn,*args,**kwargs):
    try:
        result=fn(*args,**kwargs)
        st.success('Saved successfully.')
        return result
    except Exception as exc:
        st.error(str(exc) if isinstance(exc,ValueError) else 'Request failed. Check configuration; private service details are withheld.')
        return None


def bridge(owner,destination,label):
    # Called only after the application verified this Streamlit session.
    st.link_button(label,identity.issue_bridge(owner,destination))
    st.caption('One-use sign-in link, valid for 60 seconds. Refresh this page for a new link. Your account ID is never used as an authentication credential.')


def verify(owner):
    with st.expander('Verify password for sensitive actions',expanded=not st.session_state.get('account_proof')):
        with st.form('account_step_up'):
            password=st.text_input('Verify your account password',type='password')
            submit=st.form_submit_button('Verify for ten minutes')
        if submit:
            proof=attempt(identity.step_up,owner,password)
            if proof:
                st.session_state.account_proof=proof
    return st.session_state.get('account_proof','')


def profile_page(owner):
    st.title('My Profile')
    item=identity.profile(owner)
    st.caption('Private account information · '+item['id'])
    with st.form('my_profile'):
        name=st.text_input('Full name',value=item['full_name'],max_chars=120)
        company=st.text_input('Company / organization name',value=item['company'],max_chars=120)
        job=st.text_input('Job title',value=item['job_title'],max_chars=120)
        a,b=st.columns(2)
        country=a.text_input('Country',value=item['country'],max_chars=120)
        timezone=b.text_input('Timezone',value=item['timezone'],help='IANA identifier, for example Europe/Berlin')
        if st.form_submit_button('Save profile',type='primary'):
            attempt(identity.save_profile,owner,name,company,job,country,timezone)
    st.write('Email: '+item['email']+(' · Verified' if item['email_verified'] else ' · Not verified'))
    st.write('Account created: '+pd.to_datetime(item['created'],unit='s',utc=True).strftime('%d %b %Y %H:%M UTC'))
    st.caption('Immutable account ID: '+owner)
    if st.button('Send email verification',disabled=not identity.email_ready()):
        attempt(identity.request_email,'verify',owner=owner)
    current=billing.account(owner);usage=billing.usage(owner)
    a,b,c=st.columns(3)
    a.metric('Subscription plan',current['plan'].title());b.metric('Status',billing.status_label(current));c.metric('AI requests',f"{usage['ai_requests']} / {usage['limits']['ai_requests']}")
    st.caption(f"Cycle: {current.get('interval') or 'None'} · Files: {usage['files']} / {usage['limits']['files']} · Storage: {usage['storage_bytes']/1048576:.2f} / {usage['limits']['storage_mb']} MiB")
    bridge(owner,'/workspace/settings/billing','Manage subscription, payment methods and invoices')
    st.info('Change password, verified email changes, session revocation and deletion are in Account Settings.')


def settings_page(owner):
    st.title('Account Settings')
    from app.modules_ui import security_page
    security_page(owner)
    proof=verify(owner)
    st.subheader('Verified email change')
    if not identity.email_ready():
        st.info('SMTP is not configured. Verified email changes, recovery and invitations require configured delivery; no address is changed without verification.')
    with st.form('change_email'):
        email=st.text_input('New email address',max_chars=254)
        password=st.text_input('Current password for email change',type='password')
        if st.form_submit_button('Send email-change verification',disabled=not identity.email_ready()):
            attempt(identity.request_email,'change',email=email,owner=owner,password=password)
    if st.button('Revoke other active sessions'):
        changed=attempt(identity.revoke_sessions,owner,proof)
        if changed:
            st.session_state.user['issued']=time.time()
            st.session_state.pop('account_proof',None)
    bridge(owner,'/account/settings','Open account security in the companion service')
    with st.expander('Delete account'):
        st.warning('Private uploads, indexes and conversations are removed. Shared organization data and financial audit records are retained. Transfer sole organization ownership and finish any subscription cancellation first.')
        with st.form('delete_account'):
            password=st.text_input('Password to delete account',type='password')
            confirm=st.text_input('Type DELETE MY ACCOUNT')
            if st.form_submit_button('Permanently delete my account'):
                try:
                    identity.delete_account(owner,password,confirm)
                    st.session_state.clear();st.rerun()
                except Exception as exc:
                    st.error(str(exc) if isinstance(exc,ValueError) else 'Deletion could not complete.')


def admin_page(owner):
    identity.require_platform(owner)
    st.title('Admin Dashboard')
    st.caption('Platform administration · Account access is checked again on every operation. Customer document content is not exposed here.')
    proof=verify(owner)
    try:
        identity.require_step(owner,proof)
    except ValueError:
        st.info('Verify your password above to open the user directory.')
        return
    query=st.text_input('Search users by name or email',max_chars=120)
    page=int(st.number_input('User directory page',min_value=1,value=1,step=1))
    result=identity.users(owner,query,page-1,proof=proof)
    st.metric('Matching registered users',result['total'])
    if not result['data']:
        st.info('No accounts match this search.')
        return
    directory=pd.DataFrame(result['data'])
    for column in ('created','last_login'):
        directory[column]=directory[column].map(lambda value:pd.to_datetime(value,unit='s',utc=True).strftime('%d %b %Y %H:%M UTC') if value else 'Never')
    st.dataframe(directory,hide_index=True,width='stretch')
    choices={u['id']:(u['full_name'] or u['email']) for u in result['data']}
    target=st.selectbox('User details',choices,format_func=choices.get)
    detail=identity.user_detail(owner,target,proof)
    st.json(detail['user']);st.write('Subscription',detail['billing'])
    st.subheader('Organizations and activity')
    st.dataframe(pd.DataFrame(detail['organizations']),hide_index=True,width='stretch')
    st.dataframe(pd.DataFrame(detail['activity']),hide_index=True,width='stretch')
    if identity.platform_role(owner)=='super_admin':
        st.info('Use separate named tester accounts. Member tests customer billing; Admin reviews the directory; Super Admin can administer users and billing. Assign Super Admin only to trusted administrators.')
        for action,options,label in [('role',['member','admin','super_admin'],'Platform role'),('status',['active','suspended','deactivated'],'Account status'),('revoke',[],'Session revocation')]:
            with st.form('admin_user_'+action+'_'+target):
                st.subheader(label)
                current=detail['user'].get('role' if action=='role' else 'status')
                value=st.selectbox(label,options,index=options.index(current) if current in options else 0,key='admin_value_'+action+'_'+target) if options else ''
                confirmed=st.checkbox('I confirm this action for the selected account.',key='admin_confirm_'+action+'_'+target)
                if st.form_submit_button('Apply '+label.lower()):
                    if not confirmed:
                        st.error('Confirmation required.')
                    else:
                        attempt(identity.manage_user,owner,target,action,value,proof)
    else:
        st.info('Platform Admin can inspect account metadata. Role/status/session administration requires Super Admin.')
    bridge(owner,'/admin','Open /admin directory and administration')


def organization_page(owner,team_focus=False):
    st.title('Team Members' if team_focus else 'Organization')
    with st.expander('Create organization'):
        with st.form('create_org'):
            name=st.text_input('Organization name',max_chars=120)
            if st.form_submit_button('Create organization'):
                attempt(organizations.create,owner,name)
    available=organizations.list_for(owner)
    if not available:
        st.info('Create an organization or accept a verified invitation. Your personal workspace remains private.')
        return
    choices={o['id']:o['name'] for o in available}
    oid=st.selectbox('Organization workspace',choices,format_func=choices.get)
    role=organizations.require(owner,oid)
    st.caption('Your organization role: '+role+' · Private billing remains account-scoped.')
    member_list=organizations.members(owner,oid)
    st.dataframe(pd.DataFrame(member_list),hide_index=True,width='stretch')
    if role in {'owner','manager'}:
        with st.form('org_rename'):
            name=st.text_input('Organization display name',value=choices[oid],max_chars=120)
            if st.form_submit_button('Save organization'):
                attempt(organizations.rename,owner,oid,name)
        with st.form('invite_org'):
            email=st.text_input('Invite email',max_chars=254)
            invite_role=st.selectbox('Invitation role',['member','viewer','manager','owner'] if role=='owner' else ['member','viewer'])
            if st.form_submit_button('Send verified invitation',disabled=not identity.email_ready()):
                attempt(organizations.invite,owner,oid,email,invite_role)
        if not identity.email_ready():
            st.info('Configure SMTP before sending invitations. Members are never added by an unverified email parameter.')
        proof=verify(owner)
        with st.form('org_membership_change'):
            target=st.selectbox('Manage organization member',[m['id'] for m in member_list],format_func={m['id']:m['email'] for m in member_list}.get)
            newrole=st.selectbox('Organization role',['owner','manager','member','viewer','remove'])
            if st.form_submit_button('Update organization membership'):
                attempt(organizations.change_member,owner,oid,target,newrole,proof)
        team_list=organizations.teams(owner,oid)
        tchoices={'': 'Create new team'}|{t['id']:t['name'] for t in team_list}
        team=st.selectbox('Edit team',tchoices,format_func=tchoices.get)
        existing=next((t for t in team_list if t['id']==team),None)
        with st.form('save_org_team'):
            tname=st.text_input('Team name',value=existing['name'] if existing else '',max_chars=120)
            active_members={m['id']:m['email'] for m in member_list if m['status']=='active'}
            selected=st.multiselect('Team membership',list(active_members),default=[mid for mid in existing['members'] if mid in active_members] if existing else [],format_func=active_members.get)
            if st.form_submit_button('Save team'):
                attempt(organizations.save_team,owner,oid,tname,selected,team or None)
        if team and st.checkbox('Confirm team deletion') and st.button('Delete team'):
            attempt(organizations.delete_team,owner,oid,team)
    st.subheader('Teams')
    st.dataframe(pd.DataFrame(organizations.teams(owner,oid)),hide_index=True,width='stretch')
    st.subheader('Organization data & reports')
    st.caption('Shared datasets leave the private workspace. Only current organization members can read them; viewers cannot share or index. Teams organize members and do not grant additional data access.')
    if role!='viewer':
        private=store.datasets(owner)
        if private:
            with st.form('share_org_dataset'):
                did=st.selectbox('Private dataset to share',[d['id'] for d in private],format_func={d['id']:d['name'] for d in private}.get)
                confirm=st.checkbox('Share this data with all authorized organization members.')
                if st.form_submit_button('Share selected dataset'):
                    attempt(organizations.share_dataset,owner,oid,did,confirm)
    shared=store.datasets(owner,oid)
    if not shared:
        st.info('No shared datasets yet. Upload scanned files in Data studio, then share them here.')
    else:
        did=st.selectbox('Shared dataset',[d['id'] for d in shared],format_func={d['id']:d['name'] for d in shared}.get)
        item=store.dataset(owner,did,oid)
        if item['kind']=='table':
            from cortex import data
            frame,rejected=data.validate_records(item['payload']['rows'])
            if not frame.empty:
                a,b,c=st.columns(3)
                dates=a.date_input('Organization report dates',(frame.date.min().date(),frame.date.max().date()))
                products=b.multiselect('Organization products',sorted(frame['product'].unique()))
                customers=c.multiselect('Organization customer references',sorted(frame['customer_id'].unique()))
                if len(dates)==2:
                    frame=data.filter_records(frame,*dates,products,customers)
                    st.dataframe(frame,hide_index=True,width='stretch')
                    st.bar_chart(frame.groupby('product')['revenue'].sum())
                    st.download_button('Download organization report',data.safe_csv(frame),'organization-report.csv','text/csv')
            else:
                st.dataframe(pd.DataFrame(item['payload']['rows']),hide_index=True,width='stretch')
        else:
            st.text(item['payload']['text'][:20000])
        if role!='viewer' and st.button('Build organization BM25 index'):
            from cortex.retrieval import build_index
            attempt(build_index,owner,did,'bm25',oid)
        with st.form('organization_carol'):
            question=st.text_input('Ask Carol about this organization dataset',max_chars=2000)
            if st.form_submit_button('Ask organization Carol'):
                from cortex.agents import run_agents
                result=attempt(run_agents,owner,question,dataset_id=did,organization=oid)
                if result:
                    st.markdown(result['answer'])
        with st.expander('My organization conversations'):
            for message in reversed(store.history(owner,'messages',20,oid)):
                st.write(message['question']);st.write(message['answer'])
        if role in {'owner','manager'} and st.checkbox('Confirm shared dataset deletion') and st.button('Delete shared dataset'):
            attempt(store.delete_dataset,owner,did,oid)
    if role=='owner':
        with st.expander('Delete organization'):
            confirmed=st.checkbox('Confirm deleting this organization and its memberships')
            if st.button('Delete organization'):
                attempt(organizations.delete_organization,owner,oid,st.session_state.get('account_proof',''),confirmed)
    bridge(owner,'/organizations','Open organization links and invitation acceptance')
