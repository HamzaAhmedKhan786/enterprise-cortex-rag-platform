# Cortex product requirements

## Problem and audience

Support managers and operations teams work across spreadsheets, policies and logistics tools. They need reproducible business metrics, source-backed answers and a record of how recommendations were produced.

## Before this release

The original app exposed three unauthenticated Streamlit pages over one PostgreSQL dataset and a shared Pinecone index. Warehouse SQL, deployment and evaluation templates existed, but the advertised end-to-end enterprise workflow was not verified.

## Implemented workspace release

| Capability | Behavior |
|---|---|
| Identity | Signup/login, salted PBKDF2 hashes, five-attempt lockout, eight-hour session, logout |
| Workspace ownership | Dataset, chunk, audit, run and chat access scoped by account ID |
| Raw upload | CSV/flat JSON/XLSX/PDF/TXT; bounded parsing, SHA-256 deduplication, immutable source versions |
| Data quality | Missing cells, duplicate rows, schema readiness, rejected date/revenue rows |
| Recommendation | Explainable deterministic heuristic; customer selects BM25, parent-child or local dense hybrid |
| Retrieval | Scoped local indexes, RRF hybrid fusion, explicit lexical coverage reranking and evidence IDs |
| Analytics | Inclusive dates, product/customer filters, eight chart types, grouped and underlying CSV reports |
| Strategies | Explicit SLA, contribution-margin and concentration rules with evidence and suggested investigations |
| Copilot | Actual LangGraph policy/tool/answer/verification path, LangChain local model option, deterministic fallback |
| Tracking | Index lifecycle, evaluation events, run duration/status, local chat history and feedback |
| External apps | Admin-only RouteMind read adapter verified against its repository; market gateway contract |
| Privacy | Cloud receives only finite allowlisted aggregate numbers; small cohorts blocked; cloud document RAG disabled |
| Observability | Optional metadata-only Langfuse SDK adapter; internal Prometheus exporter and provisioned Grafana dashboard |
| Evaluation | Retrieval smoke tests and optional deterministic DeepEval citation metric |

## Acceptance criteria

### Connected module increment

Subscriptions use Stripe-hosted checkout/portal and signed, replay-safe, authoritative-state webhooks. Security now exposes privacy consent, password changes and session revocation. Snowflake supports confirmed, administrator-only import/export with bounded reads and no overwrite/duplicate append. RouteMind plans can be assigned per workspace and polled at 30-second intervals. Carol supplies trusted FAQs and custom evidence/analytics queries. Customer uploads require static inspection plus local ClamAV and produce record-aware or binary-exact parts at the inclusive 10-MiB threshold. SDK installation does not imply provider connectivity; runtime configuration is explicit. Details and limits are in `MODULES_GUIDE.md`.

- A new account sees no other account's data and starts empty.
- Changing a date/product/customer filter changes metrics, charts and exports consistently.
- Failed indexing is recorded and never shown as ready.
- An index and original source are separate; selecting a strategy does not overwrite raw data.
- Answers carry evidence or abstain; generated prose is marked as interpretation.
- No raw prompt, file, identifier or arbitrary text can enter the cloud explanation payload.
- Unconfigured integrations show an honest disconnected state.
- Demo data is explicitly synthetic and belongs to the account that loads it.

## Scope limits and next phases

This is a single-node enterprise-oriented foundation, not a certified or hardened multi-tenant SaaS. Workspaces currently equal individual accounts, not organizations with shared roles. Next: OIDC/SSO/MFA, verified email and password recovery, PostgreSQL RLS/migrations, encrypted object storage, distributed jobs, quotas enforced at the gateway, structured retention and backup deletion, malware scanning, OCR, column mapping, multi-currency and audited accounting definitions.

The recommender includes optional local AI advice from a bounded sample, but is not yet an AI benchmark optimizer. Human-reviewed question sets, candidate index comparisons, neural reranking, GraphRAG, contextual enrichment and cost-quality evaluation remain roadmap work. Cortex Analyst/Search and full Snowflake ingestion are not wired to this UI. Existing Pinecone scripts remain legacy and do not provide workspace isolation; do not expose them as customer endpoints.

RouteMind plans are not carrier tracking. Live shipment GPS/ETA requires an authenticated carrier/TMS feed. Market analysis requires a chosen provider, credentials and licensing. Kafka/RabbitMQ are intentionally absent: first establish durable job semantics, retries and dead-letter handling, then select one broker based on measured scale and event replay needs.

## Success measures

Track retrieval hit@5/MRR over reviewed questions, correct abstentions, numeric reconciliation, p95 response latency, failed jobs, dataset freshness and helpfulness feedback. Do not describe one smoke test as a measured quality improvement.

## Stripe billing increment

Implemented: Free/Pro/Team/Enterprise catalog with configurable monthly and annual Stripe Price references; authenticated pricing, billing overview, card-management, invoice and usage routes; a platform billing dashboard with per-account password step-up; backend file/storage/request allowances; signed subscription/invoice lifecycle synchronization and duplicate-checkout protection. Defaults describe application quotas, not approved commercial pricing. Card entry, replacement, billing details, plan changes and cancellations use Stripe-hosted interfaces.

Acceptance: automated lifecycle/authorization tests are separate from hosted provider validation. Stripe Test Mode checkout, portal settings, proration, 3DS, test-clock renewals and actual invoice downloads require the operator to configure test credentials/products/webhook forwarding and execute the guide in STRIPE_BILLING.md. No live payment or organization billing is claimed. Token-cost accounting, BYOK, organization memberships and production MFA remain pending.
