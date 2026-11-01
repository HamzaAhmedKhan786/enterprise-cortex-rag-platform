"""Organization ACLs. No implicit platform-admin access to customer contents."""
import secrets
import time
from cortex import identity, store


def require(owner,organization,write=False,manage=False,db=None):
    def check(conn):
        identity.active(owner,conn)
        row=conn.execute('SELECT role FROM memberships WHERE owner=? AND organization=?',(owner,organization)).fetchone()
        allowed={'owner','manager'} if manage else {'owner','manager','member'} if write else identity.ORG_ROLES
        if not row or row[0] not in allowed:
            raise ValueError('Organization permission denied.')
        return row[0]
    if db is not None:
        return check(db)
    with store.connection() as conn:
        return check(conn)


def list_for(owner):
    identity.active(owner)
    with store.connection() as db:
        return [dict(r) for r in db.execute('SELECT o.*,m.role FROM organizations o JOIN memberships m ON m.organization=o.id WHERE m.owner=? ORDER BY o.name',(owner,))]


def create(owner,name):
    name=name.strip()
    if not name or len(name)>120:
        raise ValueError('Organization name must contain 1–120 characters.')
    oid=secrets.token_hex(16)
    with store.connection() as db:
        identity.active(owner,db)
        db.execute('INSERT INTO organizations VALUES(?,?,?)',(oid,name,time.time()))
        db.execute("INSERT INTO memberships VALUES(?,?,'owner')",(oid,owner))
    store.audit(owner,'organization_created',oid)
    return oid


def rename(owner,organization,name):
    if not name.strip() or len(name)>120:
        raise ValueError('Use an organization name of 1–120 characters.')
    with store.connection() as db:
        require(owner,organization,manage=True,db=db)
        db.execute('UPDATE organizations SET name=? WHERE id=?',(name.strip(),organization))
    store.audit(owner,'organization_renamed',organization)


def members(owner,organization):
    with store.connection() as db:
        require(owner,organization,db=db)
        return [dict(r) for r in db.execute("SELECT u.id,u.email,COALESCE(p.full_name,'') full_name,u.status,m.role FROM memberships m JOIN users u ON u.id=m.owner LEFT JOIN profiles p ON p.owner=u.id WHERE m.organization=? ORDER BY u.email",(organization,))]


def invite(owner,organization,email,role='member'):
    email=store._email(email)
    if role not in identity.ORG_ROLES:
        raise ValueError('Invalid organization role.')
    if not identity.email_ready():
        raise ValueError('Configure SMTP to deliver verified invitations.')
    token=secrets.token_urlsafe(32)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        actor_role=require(owner,organization,manage=True,db=db)
        if actor_role!='owner' and role in {'owner','manager'}:
            raise ValueError('Only an organization owner can invite owners/managers.')
        identity._throttle(db,'invite:'+owner+':'+organization)
        db.execute('INSERT INTO invitations VALUES(?,?,?,?,?,?)',(identity.digest(token),organization,email,role,owner,time.time()+86400))
    from cortex.billing import _base_url
    try:
        identity.deliver(email,'Cortex organization invitation',f'Sign in or register a Cortex account using this email, then accept within 24 hours:\n{_base_url()}/auth/invitation#token={token}')
    except Exception:
        with store.connection() as db:
            db.execute('DELETE FROM invitations WHERE digest=?',(identity.digest(token),))
        raise ValueError('Invitation delivery failed. No membership was granted.') from None
    store.audit(owner,'organization_invitation_sent',organization,{'role':role})


def accept(owner,token):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');user=identity.active(owner,db)
        row=db.execute('SELECT * FROM invitations WHERE digest=?',(identity.digest(token),)).fetchone()
        if not row or row['expires']<=time.time() or row['email']!=user['email']:
            raise ValueError('Invitation is invalid, expired or belongs to another email.')
        inviter=require(row['inviter'],row['organization'],manage=True,db=db)
        if row['role'] in {'owner','manager'} and inviter!='owner':
            raise ValueError('Inviter no longer has the necessary permission.')
        # A stale invitation can never overwrite an existing member's role.
        db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?)',(row['organization'],owner,row['role']))
        db.execute('UPDATE users SET email_verified=? WHERE id=?',(time.time(),owner))
        db.execute('DELETE FROM invitations WHERE digest=?',(identity.digest(token),))
        organization=row['organization']
    store.audit(owner,'organization_invitation_accepted',organization)
    return organization


def change_member(owner,organization,target,role,proof):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');actor_role=require(owner,organization,manage=True,db=db);identity.require_step(owner,proof,db)
        current=db.execute('SELECT role FROM memberships WHERE organization=? AND owner=?',(organization,target)).fetchone()
        if not current or role not in identity.ORG_ROLES|{'remove'}:
            raise ValueError('Unknown member or role.')
        if actor_role!='owner' and (current[0] in {'owner','manager'} or role in {'owner','manager'}):
            raise ValueError('Only an owner can manage owners/managers.')
        if current[0]=='owner' and role!='owner' and db.execute("SELECT COUNT(*) FROM memberships m JOIN users u ON u.id=m.owner WHERE organization=? AND role='owner' AND u.status='active'",(organization,)).fetchone()[0]<=1:
            raise ValueError('Transfer ownership before removing the last active owner.')
        if role=='remove':
            db.execute('DELETE FROM memberships WHERE organization=? AND owner=?',(organization,target))
        else:
            db.execute('UPDATE memberships SET role=? WHERE organization=? AND owner=?',(role,organization,target))
    store.audit(owner,'organization_membership_changed',target,{'organization':organization,'role':role})


def teams(owner,organization):
    with store.connection() as db:
        require(owner,organization,db=db)
        rows=[dict(r) for r in db.execute('SELECT * FROM teams WHERE organization=? ORDER BY name',(organization,))]
        for row in rows:
            row['members']=[r[0] for r in db.execute('SELECT owner FROM team_members WHERE team=? AND organization=?',(row['id'],organization))]
        return rows


def save_team(owner,organization,name,member_ids,team=None):
    if not name.strip() or len(name)>120 or len(member_ids)>500:
        raise ValueError('Use a team name of 1–120 characters and at most 500 members.')
    team_id=team or secrets.token_hex(16)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');require(owner,organization,manage=True,db=db)
        if team and not db.execute('SELECT 1 FROM teams WHERE id=? AND organization=?',(team,organization)).fetchone():
            raise ValueError('Team is unavailable in this organization.')
        for mid in set(member_ids):
            require(mid,organization,db=db)
        db.execute('INSERT INTO teams VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',(team_id,organization,name.strip()))
        db.execute('DELETE FROM team_members WHERE team=?',(team_id,))
        db.executemany('INSERT INTO team_members VALUES(?,?,?)',[(team_id,organization,mid) for mid in set(member_ids)])
    store.audit(owner,'team_saved',team_id,{'organization':organization})
    return team_id


def delete_team(owner,organization,team):
    with store.connection() as db:
        require(owner,organization,manage=True,db=db)
        db.execute('DELETE FROM teams WHERE id=? AND organization=?',(team,organization))
    store.audit(owner,'team_deleted',team,{'organization':organization})


def share_dataset(owner,organization,dataset_id,confirmed=False):
    if not confirmed:
        raise ValueError('Confirm sharing with all authorized organization members.')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');require(owner,organization,write=True,db=db)
        row=db.execute('SELECT 1 FROM datasets WHERE owner=? AND id=?',(owner,dataset_id)).fetchone()
        if not row or db.execute('SELECT 1 FROM organization_datasets WHERE dataset=?',(dataset_id,)).fetchone():
            raise ValueError('Only an unshared private dataset you own can be shared.')
        db.execute('INSERT INTO organization_datasets VALUES(?,?)',(dataset_id,organization))
    store.audit(owner,'dataset_shared_with_organization',dataset_id,{'organization':organization})


def delete_organization(owner,organization,proof,confirmed=False):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');role=require(owner,organization,manage=True,db=db);identity.require_step(owner,proof,db)
        if role!='owner' or not confirmed:
            raise ValueError('An owner must explicitly confirm organization deletion.')
        if db.execute('SELECT 1 FROM organization_datasets WHERE organization=?',(organization,)).fetchone():
            raise ValueError('Delete shared datasets first; organization deletion never silently erases shared records.')
        db.execute('DELETE FROM feedback WHERE run_id IN (SELECT id FROM runs WHERE organization=?)',(organization,))
        db.execute('DELETE FROM messages WHERE organization=?',(organization,))
        db.execute('DELETE FROM runs WHERE organization=?',(organization,))
        db.execute('DELETE FROM organizations WHERE id=?',(organization,))
    store.audit(owner,'organization_deleted',organization)
