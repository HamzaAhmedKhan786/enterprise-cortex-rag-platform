"""Create isolated screenshot fixtures; never writes the application's normal database."""
import json
import os
from pathlib import Path
import secrets
import sys

if '--isolated-qa' not in sys.argv:
    raise SystemExit('Pass --isolated-qa to create disposable browser-test fixtures.')
root=Path(__file__).resolve().parents[1]
private=root/'data/private/account-capture'
private.mkdir(parents=True,exist_ok=True)
path=private/'workspace.sqlite3'
if path.exists():
    raise SystemExit('Existing capture database found; stop its QA servers and remove it explicitly before recreating.')
os.environ['CORTEX_DB']=str(path)
os.environ.pop('CORTEX_ADMIN_USER_ID',None)
sys.path.insert(0,str(root))
from cortex import identity,organizations,store
store.initialize()
password=secrets.token_urlsafe(32)
admin=store.signup('qa-admin@example.test',password)['id']
tester_password=secrets.token_urlsafe(32)
member=store.signup('qa-member@example.test',tester_password)['id']
identity.save_profile(admin,'QA Administrator','Isolated QA workspace','Analyst','Germany','Europe/Berlin')
identity.save_profile(member,'QA Member','Isolated QA workspace','Member','Germany','Europe/Berlin')
os.environ['CORTEX_ADMIN_USER_ID']=admin
store.initialize()
organization=organizations.create(admin,'Isolated QA Organization')
# Exercise the real verified-invitation code with an in-memory email transport.
os.environ['SMTP_HOST']='localhost';os.environ['SMTP_FROM']='qa@example.test'
sent=[]
identity.deliver=lambda address,subject,body:sent.append(body)
organizations.invite(admin,organization,'qa-member@example.test','member')
invitation=sent[-1].split('#token=')[1].strip()
organizations.accept(member,invitation)
organizations.save_team(admin,organization,'QA Operations',[admin,member])
(private/'credentials.json').write_text(json.dumps({'admin':admin,'email':'qa-admin@example.test','password':password,'tester':member,'tester_email':'qa-member@example.test','tester_password':tester_password,'database':str(path)}),encoding='utf-8')
print('Created isolated QA fixtures; credentials remain in ignored private storage.')
