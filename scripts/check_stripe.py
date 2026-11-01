"""Inspect Stripe without exposing keys; optionally configure an app-specific test portal."""
import argparse
import json
from pathlib import Path
import sys
from dotenv import load_dotenv,set_key
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));load_dotenv(root/'.env')
from cortex import billing_setup,store
parser=argparse.ArgumentParser()
parser.add_argument('--configure-test-portal',action='store_true')
parser.add_argument('--probe-webhook',action='store_true')
args=parser.parse_args();store.initialize()
try:
    if args.configure_test_portal:
        config=billing_setup.configure_test_portal()
        set_key(str(root/'.env'),'STRIPE_PORTAL_CONFIGURATION',config)
        import os
        os.environ['STRIPE_PORTAL_CONFIGURATION']=config
        print('Created/selected the Cortex Test Mode portal and saved its non-secret configuration reference. Restart the application services.')
    if args.probe_webhook:
        print(json.dumps(billing_setup.probe_test_webhook(),indent=2))
    print(json.dumps(billing_setup.diagnose(),indent=2))
except Exception as exc:
    print('Stripe check failed: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    raise SystemExit(1)
