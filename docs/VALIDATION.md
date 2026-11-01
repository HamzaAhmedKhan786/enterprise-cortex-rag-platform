# Stripe access and configuration repair

- Full combined suite: **80 passed**, **82% cortex coverage**, followed by **47 account/billing tests passed** after the final probe and step-up hardening (83 unique test cases in total). Added regressions cover multiple named Super Admins, immediate financial-access revocation, shared recent verification, preserved allowlisted login destinations, confirmed owner-scoped checkout expiry and test-only portal configuration.
- Live read-only Stripe **Test Mode** checks confirmed all six configured prices active, unique, EUR, and correctly monthly/yearly. The previous default portal had subscription changes disabled. A separate Cortex test portal was created with all six prices and the required features; no default portal, payment, invoice amount or customer payment method was changed.
- One linked customer had an open Checkout and no subscription. The Free plan was therefore expected. No successful payment/renewal is claimed.
- Local CLI startup failed because the installed version requires explicit events. The helper now supplies them and privately synchronizes the signing secret. WebSocket timeouts are reported as connection warnings rather than hidden. Test Mode setup and key handling are documented in STRIPE_BILLING.md.
- Billing now checks persistent Super Admin role plus recent password verification at both route and domain layers. The old single-operator billing check was an application limitation, not a bad Stripe key. Shared passwords are not introduced. Platform Admin does not receive financial write access.
- A genuine Test Mode portal metadata event was emitted by Stripe, forwarded by the CLI, signature-verified and recorded by the local API; the marker was restored. No payment was created. Additional probe safety tests cover metadata restoration and rejection of live/unowned configurations. Older-session step-up handling was checked separately. Concurrent revocation cannot mint a fresh admin proof, and an authorized administrator can stop renewal for a suspended customer without reopening that customer’s login.
- New browser screenshots `35`–`37` use isolated local accounts and validate tester promotion/login, Stripe configuration display, available pricing, and revocation. No production account is impersonated. Actual payment/3DS/renewal acceptance remains outstanding.

## Previous account increment validation

# Account and organization validation · 2026-11-01

- Final full regression: **76 passed**, **82% cortex coverage**, Python 3.12.10. Existing billing tests remain passing. A subsequent focused delegated-admin HTTP check passed after navigation/403 refinements. Commands: `python -m pytest tests -q --cov=cortex --cov-report=term-missing --cov-report=xml` and the targeted account-scope regression.
- Covered: existing-account migration and PBKDF2-to-Argon2 upgrades; registration/login/profile persistence; reset/change/verify email tokens, expiry/replay and throttling; SMTP certificate validation with mocked transport; primary-ID bootstrap; platform role/status/session changes, protected primary/last Super Admin; step-up expiry; private/organization dataset/index/report/chat isolation; viewer restrictions, last-owner/team membership safeguards; one-use handoff, destination allowlisting and revocation races; deletion, pending-checkout/subscription guards; native profile/admin/organization/team navigation.
- Chrome exercised the actual sign-in forms, profile save/persistence, identity handoff into the companion service, administrator password verification, user-directory/user-detail routes, page refresh/navigation and a 390px mobile profile without horizontal overflow. Screenshots `26`–`34` use an isolated QA database; real registered users and customer files were not copied or impersonated.
- Compilation, `git diff --check`, JavaScript syntax checks and `pip check` pass. No actual SMTP emails, Stripe payments, warehouse transfers or live logistics calls were made. Email tests use mocked transport; SMTP is unconfigured on this host. The existing configured primary administrator ID is preserved.
- Remaining: production MFA/SSO, PostgreSQL RLS/distributed deployment, operational email delivery, global abuse controls, encrypted backups/storage, per-team content ACLs, pooled organization billing and provider/backup deletion handling. Full behavior/configuration: [ACCOUNTS_ADMIN_GUIDE.md](ACCOUNTS_ADMIN_GUIDE.md).

## Previous billing release validation

# Stripe billing validation · 2026-10-31

- Final clean full regression run: **58 passed**, **82% cortex coverage**, Python 3.12.10 (`pytest tests -q --cov=cortex --cov-report=term-missing --cov-report=xml`). Billing contributes 23 cases; original 35 tests remain passing. XML coverage is generated locally, not committed. The final browser referrer-policy correction was additionally checked with focused login/header tests and a real Chrome sign-in.
- Billing tests cover monthly/annual checkout requests and open/completed session reuse; real Stripe HMAC verification, bad signatures/test-live mismatch, retryable reconciliation failure, event replay and reversed invoice delivery; active/trialing/past-due/unpaid/canceled/incomplete entitlements; renewal/upgrade/downgrade/cancellation mapping; customer-bound cards/default/removal/hosted portal; invoices/PDF links/cursors; CSRF, origin, login/logout, expiry/password revocation, admin role/step-up/confirmation/audit; configurable limits, price disable and concurrent quota reservations; repeatable migrations and payment references.
- Stripe API transport is mocked in automated tests. **No real Stripe Checkout payment, card setup, 3DS/decline, portal plan change, test-clock renewal or PDF download was executed.** The user confirmed test credentials/products are not configured. Manual setup/acceptance procedure: [STRIPE_BILLING.md](STRIPE_BILLING.md).
- Real Chrome billing login returned HTTP 303 with a same-origin form Origin; all five customer billing pages returned HTTP 200, and a 390px mobile pricing view had no horizontal overflow. Screenshot QA found and corrected a no-referrer/Origin:null login rejection; the final same-origin referrer policy retains strict CSRF/origin validation. Local `/pricing` and application health returned HTTP 200. Screenshots show the real empty, unconfigured Free workspace; they do not simulate successful billing. Python compilation and `git diff --check` pass.
- Token usage/provider cost, BYOK, organization billing, broad RBAC and production MFA are not implemented by this increment. Admin billing uses individual password reauthentication and an operator-assigned existing user ID; no primary administrator is silently created or assigned by email.

## Previous connected-module validation

# Validation record — workspace release

## Connected modules — 31 October 2026

- Previous complete suite: **35 passed**, **79% cortex coverage**, Python 3.12.10. Includes subscription SDK contracts, real Stripe HMAC signature rejection/replay tests, authoritative status mapping, password/session revocation, static-content rejection, exact size boundaries/UTF-8/CSV splitting, atomic registration, scanner-unavailable rejection, admin/identifier/confirmation gates, mocked Snowflake import/export and idempotent export retry, workspace logistics assignments, named module agents, actual DeepEval, and UI navigation/privacy consent/admin views. Provider SDK calls are mocked; no payment or warehouse movement occurred.
- Installed and dependency-checked Langfuse 3.15.0, DeepEval 3.9.9, Stripe 14.4.2, Snowflake Connector 4.8.1 and FastAPI 0.162.0. `pip check` reports no broken requirements. The real local DeepEval example returned score 1.0 and passed; no cloud judge was used.
- Updated browser walkthrough completed with synthetic data and refreshed screenshots, including Carol, Subscriptions, Security, Snowflake access, logistics access, and SDK controls. The original two user-supplied README images remain unchanged. No customer records or credentials appear in captures.
- Workspace health returned HTTP 200 on port 8501. The local webhook API returned `ok` on port 8503. Its `.env` loading uses the same project configuration as Streamlit.
- Stripe keys/price IDs, Snowflake credentials, Langfuse project keys, administrator ID and RouteMind URL were not configured on this host. RouteMind at localhost:8000 was unreachable. These are configuration requirements, not claimed live connections.
- ClamAV Compose configuration validates, but its container startup stalled and no scanner container became available; the attempt was stopped without restarting Docker Desktop or unrelated services. **Real antivirus scanning is not runtime-verified. Customer uploads remain blocked until local ClamAV returns a successful scan.** Tests verify the fail-closed behavior and use a mocked clean verdict only for registration/manifest contracts.
- Earlier sandbox test runs hung in the async HTTP test client; the isolated host HTTP test passed, and the final complete host suite passed. No sandbox-hung run is counted as a pass.

## Executed successfully

- Full test suite before the final local-model fallback improvement: **18 passed**, **79% coverage** over `cortex`, Python 3.12.10. Command: `python -m pytest tests -q --cov=cortex --cov-report=term-missing --cov-report=xml`.
- After the fallback improvement, the targeted fallback/metadata-exporter and complete connector/privacy/parser regression set passed: **6 passed**. The suite now contains 19 tests; a new whole-suite coverage percentage is not claimed from that targeted run.
- Auth/lockout, account isolation, deduplicated ingestion, index deletion/failure, inclusive mixed-date filters, cloud aggregate policy, export formula protection, same-source table analytics/retrieval, currency rejection, actual LangGraph persistence, XLSX parsing and blank-PDF rejection.
- Connector contract tests with mocked RouteMind responses and market freshness checks; outbound cloud request inspected to ensure private names, addresses, identifiers, labels and user questions are absent. No real cloud API was called by tests.
- Streamlit AppTest: actual signup, populated dashboard, product filtering, navigation across all eight sections, logout and session expiry.
- Isolated Chrome walkthrough: generated account, synthetic records, index build, real BM25 search, evidence-only copilot answer, operations/governance screens and mobile layout. **12 screenshots** saved under `docs/screenshots`. Final walkthrough exited successfully, including workspace-data cleanup.
- Actual local dense hybrid indexing/retrieval with the cached MiniLM model: two policy chunks built, one relevant hit returned for a refund question. Cold import/index/search took approximately 95.7 seconds on this host. This is a functional smoke test, not a quality or performance benchmark.
- Docker Compose configuration parsed successfully; Git diff whitespace and Python syntax checks passed.

## Actual service limitations observed

- Local LangChain/Ollama generation reached the service but timed out at the configured 60-second read limit. The app now retains deterministic evidence as a clearly labeled degraded response if local generation is unavailable; final targeted regression tests cover this path. No successful generated answer is claimed for this host.
- Docker engine reported version 29.5.3, but both `default` and `desktop-linux` builders failed to list workers with `DeadlineExceeded`. Image build stalled before installation and was stopped without restarting Docker Desktop or unrelated containers. **The container image and Grafana/Prometheus stack were not run successfully here.**
- No configured RouteMind server/plan ID or licensed market provider was supplied. Their adapters are contract-tested, not verified as live connections.
- Langfuse and DeepEval adapters are optional. No configured Langfuse server, real trace delivery, installed DeepEval evaluation run, cloud answer quality, Snowflake/dbt execution, Cortex Search/Analyst or production deployment is claimed.

## Review guidance

The public-production blockers and unimplemented advanced features are listed in `REMAINING_WORK.md`. Screenshots use synthetic data and show actual runtime behavior; they do not imply external service readiness. The prior unauthenticated app is preserved only as a private legacy development entrypoint.
