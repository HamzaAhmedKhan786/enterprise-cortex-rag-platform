# Connected modules and activation guide

All work continues on `development`. Install the full module runtime with:

```powershell
.\.venv312\Scripts\python.exe -m pip install -r requirements-enterprise.txt
.\.venv312\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

Keep real keys in the ignored `.env` file. Use `.env.example` as a reference; do not overwrite an existing configuration. The application never creates paid Stripe plans, purchases subscriptions, migrates customer rows, or creates provider credentials during setup.

## Subscription module — SubscriptionAgent

The expanded implementation is documented in [STRIPE_BILLING.md](STRIPE_BILLING.md). It supplies real authenticated routes on the companion service (port 8503): pricing, billing overview, payment methods, invoices, usage and admin billing. Set `BILLING_BASE_URL`, test credentials, monthly/annual Pro/Team/Enterprise price IDs and webhook secret. Configure the Stripe Customer Portal for payment methods, invoices, billing details, plan changes and cancellation. Legacy Starter/Team monthly price variables remain supported.

Verified, mode-matching webhooks re-fetch current subscription/invoice state, deduplicate event IDs and authorize allowances through the billing-period end. Checkout returns and manual status refreshes cannot grant paid access. File/storage and custom AI request quotas are enforced server-side. Saved-card summaries contain only references, brand, last four and expiry; Stripe hosts card entry and replacement. Admin billing requires the existing operator-assigned account plus short-lived password re-verification. No shared administrator password is used.

Default application allowances are editable; commercial prices are configured in Stripe. No real test checkout has been executed because credentials/products were not supplied. Provider SDK calls in tests are mocked, signature verification is real, and token/provider-cost consumption is explicitly not measured. Follow the guide before accepting payments.

## Security module — SecurityAgent

The old sidebar labels were status indicators. They are now **Private workspace** and **AI data controls** buttons opening Security. Account isolation remains enforced. Users may enable numeric aggregate-only cloud explanations, change their password, revoke older sessions on their next request, and inspect configuration controls.

Raw document text, names, addresses, bank details, prompts and identifiers remain blocked from cloud AI. That block is a working policy, not a disabled feature to switch on. Internal local inference may process relevant full content. Warehouse exports and billing use separate explicit workflows, not AI inference permission.

To grant administrative connector access, copy the immutable account ID shown in Security/Governance into `CORTEX_ADMIN_USER_ID` on the server and restart. Signup email never grants administrator rights. SSO/MFA, public gateway throttling, encryption/key management and independent security testing remain production prerequisites.

## File scanning and splitting — UploadAgent

Data studio accepts up to **100 MiB** into the server's in-memory upload area. Before parsing/registering or splitting, a full-file ClamAV INSTREAM scan must succeed. Static checks then reject unsupported/executable content, script-like text, PDF JavaScript/open actions/attachments, workbook macros/embedded objects/external links/formulas, malformed formats and expansion bombs. The app does not execute uploaded code. Conservative checks may require users to upload a values-only business-data export.

```powershell
docker compose -f docker/docker-compose.yml --profile security up -d clamav
```

Local Python uses `CLAMAV_HOST=127.0.0.1`, `CLAMAV_PORT=3311`; Docker uses `clamav:3310`. ClamD's unauthenticated TCP protocol is bound to loopback/internal networking only. Its signature database must be kept current. **If ClamAV is unavailable, rejects the stream, or cannot finish, the upload is blocked.** No tool can guarantee the absence of every virus or hidden exploit; a passed scan means no known malware was detected by that scanner.

The threshold is inclusive: files **at least 10 MiB** are split into pieces **at most 9 MiB**, named `file.1.1.txt`, `file.1.2.txt`, etc.

- TXT pieces preserve UTF-8 character boundaries and can be concatenated exactly.
- CSV pieces repeat the header and preserve whole quoted/multiline records; JSON pieces are independent arrays. Combine logical rows to reconstruct their content; formatting/byte hashes may differ from the original.
- PDF/XLSX pieces end in `.part`. These are exact binary fragments, **not independently readable documents**. Concatenate them in manifest order and verify the original SHA-256 before opening. The app registers the original scanned PDF/XLSX as one bounded source; it does not parse fragments as documents.
- ZIP downloads contain parts and a manifest with method, sizes and SHA-256 hashes. Parts are generated locally only after scanning. User-supplied ZIP archives are not accepted.
- Per-workspace limits remain 50 source datasets / 100 MiB; table parts remain limited to 50,000 rows / 100 columns. PDF limits remain 200 pages, workbook expanded size 50 MiB, and document text 10 million characters. A single oversized CSV/JSON record is rejected rather than silently corrupted.

Registration pre-validates all generated sources and commits them atomically; no partial batch is accepted when parsing/quota checks fail. The scanner is a gate, not a substitute for isolated parsing workers, patched libraries and malware-response operations in production. Synthetic demo data comes from trusted application code and is not presented as antivirus-scanned customer content.

## Snowflake migration — MigrationAgent

Configure `SNOWFLAKE_ACCOUNT`, `USER`, `DATABASE`, `SCHEMA`, `WAREHOUSE`, `ROLE`, plus a password or `SNOWFLAKE_PRIVATE_KEY_FILE`. Use a least-privilege Snowflake role. Because these are shared operator credentials, both directions are restricted to `CORTEX_ADMIN_USER_ID` until per-organization connections exist.

- **Workspace → Snowflake:** explicitly confirm sending all source columns to the configured warehouse. The destination is a new account/dataset-prefixed table. Row count is checked. A completed repeat returns the prior result instead of appending again; failed/pending exports require operator reconciliation. No arbitrary SQL or overwrite option is exposed.
- **Snowflake → workspace:** allow table names through `SNOWFLAKE_ALLOWED_TABLES` (comma-separated) or import this workspace's completed export. Bound limits are 50,000 rows, 100 columns and 10 MiB; excess rows are rejected, not silently sampled. The import becomes a workspace dataset for analytics/indexing.
- Migration history records direction, destination, status and verified row count. A failed remote write may leave a Snowflake table to reconcile; local failure recording cannot roll back a remote DDL/COPY already committed by Snowflake.

These transfers are not cloud AI processing. They can include personal columns only after the explicit warehouse-transfer confirmation. The connector and contract tests do not claim a live Snowflake account was configured during development. Existing dbt/cloud warehouse loading and Cortex Analyst/Search integration remain separate work.

## Live logistics — LogisticsAgent

Start RouteMind separately and configure `LOGISTICS_BASE_URL` (for example `http://127.0.0.1:8000`). In **Live logistics**, the administrator assigns an existing RouteMind plan ID to a target immutable account ID. Ordinary users can only read their assigned plans; another account's IDs cannot be fetched through the module.

Manual refresh or optional **30-second polling while the page is open** calls the actual RouteMind API and stores a scoped numeric snapshot. Last-successful-fetch age is shown; cached snapshots older than 90 seconds are labeled stale. Failed requests never manufacture new measurements. No background Codex automation is created.

The existing RouteMind API provides delivery plans, not carrier GPS/parcel tracking. Upstream traffic/location may be simulated. A recent fetch timestamp does not make simulated data live. Real carrier shipment telemetry still requires that additional provider contract and credentials. A repository URL alone cannot supply a running endpoint or plan IDs.

## Carol chatbot — CarolAgent

The AI copilot is now **Carol**, with common product/privacy/upload/logistics FAQs, document refund/shipping shortcuts, and custom questions. Trusted platform FAQs use fixed maintained answers without an LLM. Document questions use indexed evidence; analytics questions use deterministic metrics. Local generation uses LangChain/Ollama and falls back to evidence if unavailable. Cloud aggregate explanations require the workspace's Security consent and still pass the numeric-only payload policy. Carol cannot authorize charges, migrations or shipment approvals by chat.

## Langfuse and DeepEval — ObservabilityAgent

`requirements-enterprise.txt` installs both SDKs. Operations separates **installed**, **configured** and runtime checks.

- **DeepEval:** enabled locally in the evidence verification path; run **Run DeepEval local citation test** in Operations. Telemetry is disabled before imports. The custom metric checks citation IDs only; it does not call a cloud judge or certify semantic faithfulness.
- **Langfuse:** metadata tracing is enabled when `LANGFUSE_ENABLED=true` and project keys are present. Configure `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` for a real compatible server/project. **Verify Langfuse authentication** performs an actual credentials check. An installed SDK cannot create a running server, project or keys. Only opaque run IDs, route, status and duration are traced; no prompt-capturing LangChain callbacks are attached.

Each module uses a named LangGraph agent with account checks, an explicit tool allowlist and persisted success/failure metadata. Financial, access, scanning and migration decisions are deterministic. LLMs provide language assistance through Carol, not security or payment authority.
