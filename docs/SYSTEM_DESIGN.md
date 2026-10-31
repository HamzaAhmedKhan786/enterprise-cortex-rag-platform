# System design

## Connected-module extension

See `MODULES_GUIDE.md` for implemented protocols and deployment. Stripe uses a separately hosted signed-event receiver and server-owned customer bindings; redirects never grant subscription status. Snowflake migration is confirmed/admin-only, bounded and non-overwriting, with persisted job outcomes and no repeat append after completion. RouteMind snapshots require workspace assignments and report freshness independently of upstream simulation. All modules use account-gated LangGraph tool agents; Carol alone delegates language interpretation. The upload gate scans the complete stream using local ClamAV before format parsing/splitting, rejects active-content patterns, and registers all source parts transactionally. New tables hold privacy consent, billing references/event IDs, migration metadata and assigned logistics snapshots. Password changes timestamp-revoke older sessions on their next request. Billing records remain separate from workspace-content erasure. All keys remain server configuration, not LLM context or browser-editable credentials.

## Data contracts

Tables require `date, product, customer_id, revenue`. Optional analytics fields: `cost, quantity, unit_price, category, region, status, delivery_days, promised_days`. Each row is one record, not necessarily one order. Values must use one currency (EUR in this UI). Uploads are retained intact locally, but only approved analytics columns appear in charts/exports. Unknown columns never enter AI through the analytics route.

Dates parse in UTC and are compared as normalized UTC timestamps. End dates are inclusive through the next midnight. Invalid date/revenue/product/customer rows are rejected from analytics and counted. Missing cost values prevent a full-period margin KPI; they must not be silently treated as zero. Revenue includes refunds/negative records if present and is not claimed as net accounting revenue.

## Ingestion state machine

`uploaded → indexing → ready | failed`. Index generation happens synchronously in the current Streamlit session, bounded by file/row limits. A browser disconnect or process crash can leave `indexing` pending; rebuild explicitly. This is not a durable background queue. Building vectors completes before chunk replacement, inside an ownership-checked transaction. Failed datasets retain their raw source and an operational error, not raw provider stack traces.

Limits: 10 MB/file, 50,000 table rows, 100 columns, 200 PDF pages, 2 million extracted document characters, 50 files/100 MB per account. Scanned PDFs require external OCR. XLSX uses the first sheet. JSON accepts a flat row-object array. Upload normalization can reject unsupported formats without altering an existing dataset.

## Retrieval

- BM25: local token-based baseline; lexical relevance threshold is positive BM25 score.
- Parent-child: retrieve short chunks, return bounded surrounding paragraph context.
- Hybrid: normalized local MiniLM vectors + BM25, reciprocal rank fusion, followed by lexical query-coverage ranking. Semantic candidates need cosine similarity >=0.35 when no lexical match exists. Threshold is a starting policy, not universally calibrated.
- Reranking is deterministic lexical coverage, not a cross-encoder. Neural reranking is roadmap work.
- Evidence references use dataset ID and chunk ordinal. Tables up to 2,000 rows can share their source between a descriptive row index and analytics. Larger tables remain analytics-only; no sampled table index is misrepresented as full coverage. Document indexing is capped at 4,000 chunks. Index variants are not retained side-by-side; rebuilding replaces the active configuration for that source. Compare/evaluate sequentially and record results.

No-hit responses abstain without calling a model. Local model prose is not guaranteed grounded by a prompt; evidence is shown and human review remains necessary. Local model timeouts/connection errors retain a clearly labeled deterministic evidence response and record a degraded run. Numeric analytics evidence remains visible alongside model interpretation. The verification node does not prove semantic faithfulness. DeepEval's optional citation metric checks reference validity only.

## Deterministic strategy engine

Rules flag on-time delivery below 95%, contribution margin below 20%, and largest-customer revenue share above 25%. Every signal includes its rule and selected-data evidence. Recommendations are investigations, not causal claims or autonomous execution. Changing filters changes the underlying numbers. No market or shipment facts are invented to explain a trend.

## Identity and security

Passwords: PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt, constant-time digest comparison. Account passwords are 12–256 characters. Five failed attempts per normalized email within 15 minutes lock further attempts temporarily. Sessions live in the Streamlit server session, expire after eight hours, and are cleared at logout. This is account authentication, not organization-level identity management. Add gateway rate limits, email verification, recovery, MFA and SSO before public exposure.

Tenant IDs come from authenticated session state, not form fields. Application queries parameterize values; table selections are fixed allowlists. CSV exports escape spreadsheet formula prefixes. User text never enters unsafe HTML. Server-side connector URLs cannot be chosen by ordinary users. Remote connectors require HTTPS, redirects are rejected and response size/time are bounded. RouteMind reads are administrator-only pending upstream auth/tenancy.

## Operations

Runs persist IDs, route, result, duration and content-free step descriptions. Audit rows record lifecycle metadata. Chat history is private application data, not telemetry. Observability exports only operational aggregates. Prometheus metrics are gauges of retained records, so deleting workspace data decreases counts. No personal labels appear in Grafana.

Back up the database with a consistent SQLite backup procedure, restrict filesystem access and encrypt disks/backups. Logical deletion is not forensic erasure; free pages and backups have separate retention. There is no automatic retention schedule in this release. Customer deployments must establish and disclose one.

## External contracts

RouteMind: `GET /api/health`, `GET /api/plans/{run_id}` from the supplied repository. Extract `total_distance_km`, `total_duration_minutes`, `traffic_delay_minutes`, `total_load_kg`, `estimated_cost` from route objects. No addresses, names, geometries or arbitrary narrative enter model context. The read timestamp is not a measurement timestamp and does not prove live GPS/traffic.

Market gateway: `GET /snapshot → {as_of: timezone-aware ISO8601, indicators: [{name, value, unit}]}`. Values are for display only, with a stale warning after 24 hours. Operator supplies a licensed provider/gateway. No provider has been selected or connected by default.

## Verification

Tests cover auth/lockout, tenant isolation, index deletion/failure, deduplication, filters/date boundaries, cloud egress, local endpoint policy, formula escaping and actual LangGraph persistence. UI smoke tests use Streamlit AppTest; browser captures verify actual rendered layouts when host permissions allow. External integrations are contract-tested with mocks unless credentials/endpoints are configured. Never describe unexecuted Docker/cloud/index paths as validated.
