# User and operator guide

## Start locally

Use Python 3.12 and run commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-app.txt
Copy-Item .env.example .env
streamlit run app/streamlit_app.py
```

Visit http://localhost:8501. Create your own account; no default login exists. Each account starts with an empty workspace. To explore safely, select **Load demonstration workspace**. These 540 synthetic commerce records and policy documents are clearly labeled and are not the existing PostgreSQL database or real shipments. Signup does not send email or verify ownership of the address.

## Upload and analytics

1. Open **Data studio → Upload & profile**. Choose CSV, flat JSON, XLSX, TXT or a text-based PDF. Accept only files you are authorized to process.
2. Select **Validate and register**. The original bytes remain local. The registry shows missing/duplicate data and the recommended processing path.
3. Tables need `date, product, customer_id, revenue`. Use opaque customer references and EUR values. Optional: `cost, quantity, category, region, status, delivery_days, promised_days`.
4. Open **Overview** and select the uploaded table. Filter dates, products and customer references. Every KPI and chart uses the same filtered rows.
5. **Reports** groups by product/customer/date/region and exports the filtered data. One row is one uploaded record; record count is not automatically order count. Formula prefixes are escaped in CSV exports.
6. **Decision brief** shows deterministic thresholds with supporting values. Treat suggested investigations as decision support, not automated pricing or dispatch instructions.

Unsupported schemas remain in the registry but do not appear as analytics-ready. Correct and upload a new file version. Duplicate content in the same account returns its existing version. XLSX reads the first sheet only; flatten nested JSON first. There is no UI column mapper yet.

## Knowledge and RAG

1. Expand a source in **Dataset registry**. Review its deterministic recommendation or explicitly request optional local AI advice from a bounded sample; choose a configuration and build the index. Tables up to 2,000 rows can also build a descriptive index from the same source. Aggregate numeric questions must use full-table analytics rather than retrieved row samples.
2. BM25 is fast and needs no model. Parent-child retains surrounding paragraph context. Hybrid uses BM25 and normalized local MiniLM dense vectors with reciprocal rank fusion and lexical coverage reranking.
3. Hybrid requires `sentence-transformers` and a model already cached on your server. Install optional legacy dependencies from `requirements.txt`, then provision `sentence-transformers/all-MiniLM-L6-v2` in a controlled setup step. Indexing never downloads models automatically. Keep model-cache storage separate from customer uploads.
4. Search in **Knowledge** and inspect source/chunk IDs. Evaluate a test question against an expected evidence phrase. Hit@5 and reciprocal rank are smoke-test results, not a guarantee of answer quality.
5. Changing strategy rebuilds the active index for that source; raw data remains intact. Old index variants are not preserved for side-by-side comparison yet. Deleted datasets remove their index, but prior private chat excerpts remain until workspace erasure.

## Copilot and inference choices

- **Evidence only:** default; deterministic excerpts or aggregate summaries; no model call.
- **Local Ollama:** start Ollama, provision the configured model, set `OLLAMA_HOST` and `OLLAMA_MODEL`. LangChain sends full relevant evidence and recent conversation history to the approved internal endpoint. The model may interpret evidence incorrectly; review the evidence panel. Model names and availability are operator-controlled.
- **Cloud aggregates:** analytics only. Configure `GROQ_API_KEY` and `CLOUD_MODEL`. The payload contains finite numeric totals and a fixed task, never the user's question, names, addresses, bank details, labels, document text or history. Requires at least 10 records and 5 distinct customers. No cloud document RAG is available.

The graph records policy, domain tool, response and verification stages. Feedback is stored privately. No AI agent changes orders or dispatches vehicles.

## RouteMind logistics integration

The supplied project is [RouteMind](https://github.com/HamzaAhmedKhan786/agentic-logistics-ai). Start that application separately, then configure:

```dotenv
CORTEX_ADMIN_USER_ID=your-immutable-account-id
LOGISTICS_BASE_URL=http://127.0.0.1:8000
LOGISTICS_API_KEY=
```

Only that administrator can call the connector from this UI. It calls `GET /api/health` and `GET /api/plans/{run_id}`. Enter an existing RouteMind run ID to refresh numeric route metrics. No planning/approval writes are performed. RouteMind currently has no upstream auth/tenant enforcement in the inspected API; keep it private and do not share plan access with ordinary customers.

The response timestamp is when Cortex fetched the plan. Simulated RouteMind traffic/location remains simulated. This is not a live carrier-tracking or vehicle GPS feed. A real shipment integration still requires an authenticated carrier/TMS contract, tenant mapping and credentials. This UI uses manual refresh, not SSE subscriptions.

For a market-data gateway set `MARKET_BASE_URL` and optionally `MARKET_API_KEY`. It must expose `GET /snapshot` with `{ "as_of": "2026-10-30T12:00:00Z", "indicators": [{ "name": "example", "value": 1.2, "unit": "index" }] }`. Data over 24 hours old is flagged stale. Select a licensed provider before production use.

## Docker and monitoring

```powershell
docker compose -f docker/docker-compose.yml up --build -d streamlit
# Workspace: http://localhost:8502 (local Python app stays on 8501)
# Configure a strong GRAFANA_ADMIN_PASSWORD in .env before monitoring:
docker compose --env-file .env -f docker/docker-compose.yml --profile observability up -d
```

Grafana is localhost:3001; Prometheus is localhost:9095. The internal exporter has no public port. The named workspace volume persists data. The legacy PostgreSQL profile uses host port 5433 to avoid the existing native database on 5432. Never run `down -v` unless you intend to remove persistent data.

For Langfuse, install `requirements-observability.txt`, configure host/public/secret keys and explicitly set `LANGFUSE_ENABLED=true`. The adapter targets the v3 Python SDK API; verify compatibility with your Langfuse server before enabling. Only run ID, route, status and duration are exported. Automatic LangSmith tracing is disabled on this new path. DeepEval's custom metric in `evaluation/evidence_metric.py` makes no judge/model calls and checks citation IDs only. Do not attach prompt-capturing callbacks.

After installing optional dependencies, run `python -m evaluation.evidence_metric` for a synthetic local metric example. The module sets `DEEPEVAL_TELEMETRY_OPT_OUT=1` before importing DeepEval. It calls the custom metric directly rather than the cloud-connected evaluation/reporting wrappers. Do not use external evaluation uploads for customer content without an approved processing agreement and explicit data policy.

## Tests and troubleshooting

```powershell
pip install -r requirements-dev.txt
python -m pytest tests -q --cov=cortex --cov-report=xml
```

If a restricted Windows environment cannot create pytest's system temp folder, choose a fresh folder under `data/test-temp/` using `--basetemp`. If an index fails, check the model cache or select BM25. If the assistant fails, check the provider in `.env`; the UI intentionally hides raw provider errors. If an integration is disconnected, configure its server URL and verify reachability from the container (host services require `host.docker.internal`).

Read **Governance** for storage/erasure behavior. Before exposing the service publicly, complete the production blockers in `docs/REMAINING_WORK.md`.
