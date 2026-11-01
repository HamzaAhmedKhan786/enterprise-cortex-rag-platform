# Stripe billing: setup, operation and verification

Cortex uses the official Stripe Python SDK with hosted Checkout and Customer Portal. Card numbers and CVVs never pass through Cortex. The local Stripe Test Mode key and all six configured EUR monthly/yearly prices have now been verified against Stripe. A Cortex-specific test portal has been configured. **No test payment or recurring subscription has been completed by this verification.** Automated tests use mocked Stripe transport and real Stripe signature verification.

## Start locally

```powershell
.\.venv312\Scripts\python.exe -m pip install -r requirements-enterprise.txt
# Terminal 1: application
.\.venv312\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.port 8501
# Terminal 2: authenticated billing pages + webhooks, same working directory/database
.\.venv312\Scripts\python.exe -m uvicorn cortex.api:app --host 127.0.0.1 --port 8503
```

Open `/pricing`, `/workspace/settings/billing`, `/workspace/settings/billing/payment-methods`, `/workspace/settings/billing/invoices`, `/workspace/settings/billing/usage`, and `/admin/billing` on **http://localhost:8503**. These are real backend routes, supporting refresh and browser back/forward. The Streamlit Subscriptions page links to them. Streamlit links now use a verified, one-use identity handoff; direct URLs without a companion session still require sign-in using your workspace credentials. Direct protected routes redirect to billing login; mutation endpoints reject unauthenticated requests. There is no Next.js application in this repository.

Docker: `docker compose -f docker/docker-compose.yml --profile billing up --build -d`. The app maps to localhost:8502, billing to localhost:8503. Both share `workspace_data`. Existing Docker/ClamAV setup requirements still apply.

## Configure Stripe Test Mode

1. Create/open your Stripe test environment. Create **Pro, Team and Enterprise** products with monthly and annual recurring prices. Choose your test prices explicitly; this implementation does not invent final commercial prices. Free requires no Stripe Price. Keep all price IDs unique across plans and intervals.
2. Set `.env` values: `STRIPE_SECRET_KEY=sk_test_...`, `STRIPE_PRICE_PRO_MONTHLY`, `STRIPE_PRICE_PRO_ANNUAL`, the equivalent TEAM and ENTERPRISE IDs, and `BILLING_BASE_URL=http://localhost:8503`. Existing `STRIPE_PRICE_STARTER` and `STRIPE_PRICE_TEAM` remain legacy monthly fallbacks. Blank intervals cannot be purchased. Restart both Python services after changing environment variables.
3. Enable the test Customer Portal in Stripe Dashboard: payment-method updates, invoice history, billing details, subscription changes and cancellation. Add the configured products/prices, choose proration behavior, and explicitly choose immediate or end-of-period downgrades. Portal downgrades at period end have Stripe product/pricing restrictions; test your chosen product structure. Optionally set `STRIPE_PORTAL_CONFIGURATION=bpc_...`.
4. Install and authenticate the official Stripe CLI, then run:
   ```text
   stripe login
   stripe listen --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed --forward-to http://localhost:8503/webhooks/stripe
   ```
   Put the printed **test signing secret** in `STRIPE_WEBHOOK_SECRET` and restart the billing service. CLI secrets differ from Dashboard webhook secrets.
5. For deployed test environments, register the HTTPS `/webhooks/stripe` endpoint in Stripe Workbench. Subscribe to the event types in `cortex.billing.SUB_EVENTS`, especially `customer.subscription.*`, `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, and `invoice.payment_action_required`. Use that destination's signing secret.
6. Enable cards in Stripe payment-method settings. Checkout leaves payment types dynamic so compatible additional methods can be enabled in the Stripe Dashboard by country/currency and recurring-payment compatibility. Only saved **cards** are summarized in Cortex; manage other methods in Stripe Portal. `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` is reserved in `.env.example` but **not needed** for this hosted integration.
7. Keep `STRIPE_ALLOW_LIVE=false`. Public `BILLING_BASE_URL` must use HTTPS. Use your own TLS proxy, persistence/backups and deployment secret manager before production.

## Verify the complete payment lifecycle

- Register a workspace in Streamlit, open Subscriptions → Plans & pricing, and sign into billing with the same account.
- Choose a configured monthly or annual plan. Complete Stripe Checkout using an official Stripe test card. Never use actual card details for test mode.
- Confirm CLI/Dashboard webhook delivery returns HTTP 200. The database should have a verified active subscription, product/price references and current billing period. The usage page should show the purchased allowance. Returning from checkout alone must leave paid access disabled.
- Open Payment Methods: add/replace through Stripe, retrieve safe card summaries, set a default, and remove an eligible non-default card. A default or last required card cannot be removed. Cortex applies default selection to both customer and current subscription.
- Open Invoices: verify hosted invoice/payment links, PDF download and pagination. Amounts display **minor currency units** to avoid assuming every currency uses two decimals.
- Change plans, billing interval and billing details in the Stripe Portal. Verify prorations and scheduled changes match your portal configuration, then check subscription webhooks update Cortex. Cancel and verify access continues only until the confirmed period end.
- Use Stripe test clocks / official testing tools for renewals, failed payments and recovery. Verify `past_due`/unpaid/canceled states revert to Free and a successful verified renewal restores the plan. Resend a webhook to verify duplicate handling. Invoice data is fetched again to prevent old invoice events rolling back current status.
- Sign in to Admin Billing as the assigned administrator, re-enter your own account password, and verify customer/status visibility and audit records.

## Administrator bootstrap and security

`CORTEX_ADMIN_USER_ID` must contain the **existing authenticated user's immutable account ID**, displayed in Security. For the requested primary-admin email, first sign into that existing account and verify ownership operationally; then configure its ID on the server. Signup email alone never grants privileges and no shared `admin/admin123` account is created. No administrator was automatically assigned without ownership verification.

Billing administration now uses the same persistent Super Admin role as user management. `billing_admins` is a legacy table and is not an authorization source. Changing the bootstrap environment ID does not revoke other explicitly assigned Super Admin roles; use the user directory to revoke those roles. Administrative pages and mutations also require a per-session password verification, rate-limited by existing account login protection, valid for ten minutes. This is password reauthentication, **not MFA or organization billing entitlements**. Billing admin actions currently support validated plan configuration and confirmed end-of-period cancellation, not refunds, arbitrary charges or immediate destructive cancellation.

Sessions are opaque, hashed at rest, HTTP-only, SameSite cookies with eight-hour expiry and password-change revocation. Mutations validate CSRF and request origin. All customer-facing queries derive ownership from the authenticated session. Secrets never enter HTML. Provider redirects and invoice download URLs are restricted to HTTPS Stripe domains. Logs/audits exclude card input and provider exception details.

## Persistence and entitlements

The startup migration is additive and repeatable. `billing_accounts` gains product/price IDs, interval, period bounds, cancellation flag, verification timestamp and default-method reference. New tables: `billing_plans`, `billing_invoices`, `billing_methods`, `billing_sessions`, `billing_usage`, `billing_admins`, `billing_checkouts`. Existing accounts and datasets are preserved.

Only signed, mode-matching webhooks authorize paid allowances; provider state is fetched again rather than trusting checkout query parameters, metadata ownership, or reversed event payloads. Event IDs and database transactions prevent duplicate processing. Failed reconciliation is retryable (HTTP 503), never acknowledged as success. Open checkout sessions are reused and completed sessions block a second purchase. Stripe customer, checkout and mutation requests use idempotency keys.

Default configurable allowances (not commercial prices): Free 50 files/100 MiB/100 custom AI requests per UTC month; Pro 100/500/1000; Team 500/2000/5000; Enterprise 2000/10000/20000. The legacy Starter mapping remains supported. Admin allowance changes apply immediately. Saving an admin plan configuration overrides environment price fallbacks for that plan; a blank interval then disables new purchases. Active price mappings cannot be replaced until those subscriptions are migrated. Both trusted/internal ingestion and scanned customer uploads enforce limits transactionally. Custom Carol/RAG requests reserve allowance atomically; FAQ and billing actions do not consume it. Failed requests still count. These are application quotas, **not usage-based Stripe charges**. Tokens, model cost attribution and BYOK encryption/accounting are not implemented and are not shown as measured consumption.

This remains a single-node, per-account workspace using SQLite. Billing writes and provider reconciliation serialize; multi-node SaaS needs a transactional server database and distributed job/session design. Company/team membership and scoped shared data are implemented in ACCOUNTS_ADMIN_GUIDE.md. SSO/MFA and organization-pooled billing remain separate work.

Official references: [portal configuration](https://docs.stripe.com/customer-management/configure-portal), [subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks), [test environments and cards](https://docs.stripe.com/testing).

## Verified configuration findings and repairs

The supplied test key and six EUR recurring prices are valid and unique. The previous default Stripe portal enabled cards/invoices/cancellation but disabled subscription updates. `scripts/check_stripe.py --configure-test-portal` now creates a separate application-specific **test-only** configuration with the configured products/prices, plan changes, cards, invoices, billing details and cancellation. It writes only the portal reference to the ignored `.env`; the existing account default portal is not modified. This test policy uses immediate price changes with Stripe-calculated prorations invoiced at confirmation, and cancellation at period end. Review commercial terms before live deployment; end-of-period cross-product downgrades have Stripe restrictions.

The installed CLI requires explicit event selection. A signing secret alone does not forward events to localhost; `scripts/run_stripe_listener.py` runs the installed official CLI with the needed events, keeps the API key out of argv, captures the signing secret privately, and records redacted connection status in ignored `data/private/stripe-listener/status.json`. Keep the process running while testing and restart the API after secret changes. An occasional network/WebSocket timeout was observed; inspect readiness/connection warnings and forwarding counts, and use a registered reachable HTTPS endpoint in production. CLI forwarding does not require a Dashboard webhook endpoint for localhost.

```powershell
.\.venv312\Scripts\python.exe scripts/check_stripe.py
.\.venv312\Scripts\python.exe scripts/run_stripe_listener.py
```

An open Checkout without a subscription is not a successful payment. Pricing now offers a real **Resume Stripe Checkout** link and confirmed **Cancel unfinished checkout** action so users can change plans. Completed sessions cannot be expired to start duplicate payments. Existing subscribers manage their plan in the Stripe portal; Free accounts are directed to pricing instead of a portal subscription-change action that has no subscription to modify. Empty invoice/card states do not imply a failed payment.

Billing role access is unified with user management. Super Admins use individual account credentials and the same recent password proof for `/admin` and `/admin/billing`. Direct navigation preserves the allowlisted destination through login. Platform Admin remains directory-read-only and cannot mutate billing. Each tester should register their own account; the primary administrator can assign Super Admin to a trusted tester and later revoke it. No shared `admin` password or common billing customer is created. Member is sufficient for ordinary customer Checkout tests.

### Verified webhook delivery without a payment

`python scripts/check_stripe.py --probe-webhook` temporarily marks the Cortex-owned Test Mode portal metadata, waits for the genuine Stripe event to be signature-verified and recorded locally, then restores the original metadata in `finally`. It refuses live keys and configurations owned by another application. The listener includes `billing_portal.configuration.updated` for this non-payment probe. This check passed with real Stripe delivery; it validates transport/signatures, not a completed customer purchase or renewal.

Older billing sessions with a timestamp but no current step-up proof now receive a fresh verification form instead of an internal server error. Directory and billing use the same proof once verified on the companion service.

Authorized billing cancellation remains available for suspended/deactivated customers; suspending login does not itself stop Stripe renewal. Terminal subscriptions do not expose another cancellation action.
