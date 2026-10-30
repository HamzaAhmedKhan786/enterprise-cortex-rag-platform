# Release scope and production backlog

## Implemented in the workspace release

- Local account authentication, scoped datasets/indexes/history and explicit local/cloud boundaries.
- Bounded raw upload, deterministic profiles/recommendations, selectable local retrieval configurations.
- Filtered analytics, eight chart views, reports/CSV exports and rule-based decision briefs.
- LangGraph orchestration, optional LangChain/Ollama generation and cloud aggregate explanations.
- Index/audit/run tracking, feedback, evidence tests and optional DeepEval/Langfuse adapters.
- RouteMind contract-based read adapter, market gateway contract and optional Grafana/Prometheus deployment.
- Updated README, PRD, architecture, system design, user guide and deployment privacy notice.

## Before multi-customer public production

1. OIDC/SSO/MFA, verified emails, recovery, organization membership and role permissions; edge rate limits and abuse prevention.
2. PostgreSQL RLS and migrations, encrypted object storage, managed secrets, TLS, encryption/backup lifecycle and tested restore/deletion.
3. Durable ingestion workers and job cancellation/recovery; parsing in resource-isolated sandboxes, malware scanning and security testing. Current indexing is synchronous and can be interrupted.
4. Real logistics tenant authorization and a carrier/TMS shipment feed. RouteMind currently returns delivery plans with potentially simulated inputs, not live tracking.
5. Chosen market-data provider and licensing; authenticated provider health/freshness tests.
6. Human-reviewed evaluation corpus, measured recall/MRR/groundedness, model-based faithfulness evaluation using an approved local judge, calibrated thresholds and neural reranking.
7. AI-assisted strategy comparison with measured quality/cost/latency, retained candidate index variants, contextual enrichment, GraphRAG where justified.
8. Production-grade table mapping, multi-sheet parsing, OCR, currencies, returns/taxes/order semantics and column lineage.
9. Actual Snowflake staging/loading and Cortex integration. dbt configuration is supplied but no cloud warehouse execution is claimed.
10. Observability alerts/SLOs, provider/version compatibility verification and end-to-end deployment tests. Grafana configuration alone does not demonstrate a healthy monitoring installation.

## Queue/broker decision

Do not deploy both Kafka and RabbitMQ by default. For durable ingestion tasks use a transactional job table or a task queue first. Choose RabbitMQ for delivery/acknowledgment-based worker dispatch; choose Kafka when retained event replay and multiple downstream consumers are required. Define idempotency, tenant isolation, retries and dead-letter behavior before adding either. No broker is installed in this release.
