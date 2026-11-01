"""Run a local Test Mode listener without putting API/signing keys in argv or logs."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from dotenv import load_dotenv,set_key

root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));load_dotenv(root/'.env')
from cortex import billing
private=root/'data/private/stripe-listener';private.mkdir(parents=True,exist_ok=True)
key=billing._key()
if not key.startswith(('sk_test_','rk_test_')):
    raise SystemExit('Local listener automation is limited to Stripe Test Mode.')
cli=shutil.which('stripe.exe') if os.name=='nt' else shutil.which('stripe')
if not cli and os.name=='nt':
    candidate=Path(os.getenv('APPDATA',''))/'npm/node_modules/@stripe/cli/node_modules/@stripe/cli-win32-x64/bin/stripe.exe'
    if candidate.is_file():cli=str(candidate)
if not cli:
    raise SystemExit('Install the official Stripe CLI first; see docs/STRIPE_BILLING.md.')
# OS-backed lock is released on termination; a stale lock file cannot block restart.
lock=open(private/'listener.lock','a+b')
lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
try:
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError:
    raise SystemExit('The Cortex Stripe listener is already running.')

target=billing._base_url()+'/webhooks/stripe'
from urllib.parse import urlparse
if urlparse(target).hostname not in {'localhost','127.0.0.1'}:
    raise SystemExit('Use a registered HTTPS destination for deployment, not this local helper.')
environment=dict(os.environ,STRIPE_API_KEY=key,STRIPE_DEVICE_NAME='cortex-local-test')
status={'supervisor_pid':os.getpid(),'listener_pid':None,'ready':False,'forward_to':target,'forwarded_successfully':0,'forwarding_failures':0}

def save():
    temporary=private/'status.tmp'
    temporary.write_text(json.dumps(status),encoding='utf-8');temporary.replace(private/'status.json')

proc=subprocess.Popen([cli,'listen','--events',','.join(sorted(billing.SUB_EVENTS|{'billing_portal.configuration.updated'})),'--forward-to',target],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
    text=True,encoding='utf-8',errors='replace',env=environment,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
status['listener_pid']=proc.pid;save()
try:
    for line in proc.stdout:
        secret=re.search(r'whsec_[A-Za-z0-9]+',line)
        if secret:
            set_key(str(root/'.env'),'STRIPE_WEBHOOK_SECRET',secret.group(0))
            status['ready']=True;status['secret_synced_at']=time.time();save()
            print('Stripe Test Mode listener ready; signing secret synchronized privately. Restart the API if already running.',flush=True)
        elif re.search(r'error|failed|must specify|unauthorized|forbidden',line,re.IGNORECASE):
            status['connection_warning']=True
            status['ready']=False
            cleaned=line.replace(key,'[REDACTED_KEY]')
            status['last_error']=re.sub(r'(?:[sr]k_(?:test|live)_|whsec_)[A-Za-z0-9*_-]+','[REDACTED_SECRET]',cleaned.strip())[:500];save()
        elif re.search(r'\[2\d\d\]',line):
            status['forwarded_successfully']+=1;status['ready']=True;status['connection_warning']=False;save()
        elif re.search(r'\[[45]\d\d\]|Failed to POST|connection refused',line,re.IGNORECASE):
            status['forwarding_failures']+=1;save()
    status['exit_code']=proc.wait()
finally:
    status['ready']=False;save()
    if proc.poll() is None:proc.terminate()
    lock.close()

if status.get('exit_code'):
    raise SystemExit('Stripe listener stopped; check CLI access and the private status file.')
