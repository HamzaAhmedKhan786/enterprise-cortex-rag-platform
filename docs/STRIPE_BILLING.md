# Stripe billing: setup, operation and verification

Cortex uses the official Stripe Python SDK with hosted Checkout and Customer Portal. Card numbers and CVVs never pass through Cortex. No Stripe credentials or approved commercial prices were available during development. **No real Stripe test payment has been executed yet.** Automated tests use mocked Stripe transport and real Stripe signature verification.

## Start locally

```powershell
.\.venv312\Scripts\python.exe -m pip install -r requirements-enterprise.txt
# Terminal 1: application
.\.venv312\Scripts\python.exe -m streamlit run app/streamlit_app.py --server.port 8501
# Terminal 2: authenticated billing pages + webhooks, same working directory/database
.\.venv312\Scripts\python.exe -m uvicorn cortex.api:app --host 127.0.0.1 --port 8503
```

Open `/pricing`, `/workspace/settings/billing`, `/workspace/settings/billing/payment-methods`, `/workspace/settings/billing/invoices`, `/workspace/settings/billing/usage`, and `/admin/billing` on **http://localhost:8503**. These are real backend routes, supporting refresh and browser back/forward. The Streamlit Subscriptions page links to them. Billing requires a separate sign-in using your existing workspace credentials. Direct protected routes redirect to billing login; mutation endpoints reject unauthenticated requests. There is no Next.js application in this repository.

Docker: `docker compose -f docker/docker-compose.yml --profile billing up --build -d`. The app maps to localhost:8502, billing to localhost:8503. Both share `workspace_data`. Existing Docker/ClamAV setup requirements still apply.

## Configure Stripe Test Mode

1. Create/open your Stripe test environment. Create **Pro, Team and Enterprise** products with monthly and annual recurring prices. Choose your test prices explicitly; this implementation does not invent final commercial prices. Free requires no Stripe Price. Keep all price IDs unique across plans and intervals.
2. Set `.env` values: `STRIPE_SECRET_KEY=sk_test_...`, `STRIPE_PRICE_PRO_MONTHLY`, `STRIPE_PRICE_PRO_ANNUAL`, the equivalent TEAM and ENTERPRISE IDs, and `BILLING_BASE_URL=http://localhost:8503`. Existing `STRIPE_PRICE_STARTER` and `STRIPE_PRICE_TEAM` remain legacy monthly fallbacks. Blank intervals cannot be purchased. Restart both Python services after changing environment variables.
3. Enable the test Customer Portal in Stripe Dashboard: payment-method updates, invoice history, billing details, subscription changes and cancellation. Add the configured products/prices, choose proration behavior, and explicitly choose immediate or end-of-period downgrades. Portal downgrades at period end have Stripe product/pricing restrictions; test your chosen product structure. Optionally set `STRIPE_PORTAL_CONFIGURATION=bpc_...`.
4. Install and authenticate the official Stripe CLI, then run:
   ```text
   stripe login
   stripe listen --forward-to http://localhost:8503/webhooks/stripe
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

Admin billing access is recorded in `billing_admins` only after the operator ID check. Removing/changing the environment assignment revokes access. Administrative pages and mutations also require a per-session password verification, rate-limited by existing account login protection, valid for ten minutes. This is password reauthentication, **not MFA or full organization RBAC**. Billing admin actions currently support validated plan configuration and confirmed end-of-period cancellation, not refunds, arbitrary charges or immediate destructive cancellation.

Sessions are opaque, hashed at rest, HTTP-only, SameSite cookies with eight-hour expiry and password-change revocation. Mutations validate CSRF and request origin. All customer-facing queries derive ownership from the authenticated session. Secrets never enter HTML. Provider redirects and invoice download URLs are restricted to HTTPS Stripe domains. Logs/audits exclude card input and provider exception details.

## Persistence and entitlements

The startup migration is additive and repeatable. `billing_accounts` gains product/price IDs, interval, period bounds, cancellation flag, verification timestamp and default-method reference. New tables: `billing_plans`, `billing_invoices`, `billing_methods`, `billing_sessions`, `billing_usage`, `billing_admins`, `billing_checkouts`. Existing accounts and datasets are preserved.

Only signed, mode-matching webhooks authorize paid allowances; provider state is fetched again rather than trusting checkout query parameters, metadata ownership, or reversed event payloads. Event IDs and database transactions prevent duplicate processing. Failed reconciliation is retryable (HTTP 503), never acknowledged as success. Open checkout sessions are reused and completed sessions block a second purchase. Stripe customer, checkout and mutation requests use idempotency keys.

Default configurable allowances (not commercial prices): Free 50 files/100 MiB/100 custom AI requests per UTC month; Pro 100/500/1000; Team 500/2000/5000; Enterprise 2000/10000/20000. The legacy Starter mapping remains supported. Admin allowance changes apply immediately. Saving an admin plan configuration overrides environment price fallbacks for that plan; a blank interval then disables new purchases. Active price mappings cannot be replaced until those subscriptions are migrated. Both trusted/internal ingestion and scanned customer uploads enforce limits transactionally. Custom Carol/RAG requests reserve allowance atomically; FAQ and billing actions do not consume it. Failed requests still count. These are application quotas, **not usage-based Stripe charges**. Tokens, model cost attribution and BYOK encryption/accounting are not implemented and are not shown as measured consumption.

This remains a single-node, per-account workspace using SQLite. Billing writes and provider reconciliation serialize; multi-node SaaS needs a transactional server database and distributed job/session design. Full company/team membership, SSO/MFA and organization-scoped billing remain separate work.

Official references: [portal configuration](https://docs.stripe.com/customer-management/configure-portal), [subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks), [test environments and cards](https://docs.stripe.com/testing).
