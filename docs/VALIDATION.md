# Validation record — workspace release

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
