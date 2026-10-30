# Workspace screenshots

Captured from the actual local Streamlit app using an isolated Chrome session and a generated account. Only synthetic demonstration data is shown; no real customer uploads, credentials, addresses or bank details were used. Example records are explicitly labeled in the UI.

| View | Screenshot |
|---|---|
| Sign in | [01-sign-in.png](01-sign-in.png) |
| Overview and filters | [02-overview.png](02-overview.png) |
| Detailed charts and decision brief | [03-analytics-details.png](03-analytics-details.png) |
| Grouped reports | [04-reports.png](04-reports.png) |
| Upload studio | [05-data-studio.png](05-data-studio.png) |
| Dataset profile and index | [06-index-registry.png](06-index-registry.png) |
| Search with retrieved evidence | [07-knowledge.png](07-knowledge.png) |
| Evidence-only copilot | [08-copilot.png](08-copilot.png) |
| Run and audit tracking | [09-operations.png](09-operations.png) |
| Integration configuration status | [10-integrations.png](10-integrations.png) |
| Governance and privacy | [11-governance.png](11-governance.png) |
| Mobile viewport (390 px) | [12-mobile.png](12-mobile.png) |

The screenshots demonstrate rendered pages, signup, synthetic-data loading, index creation, actual retrieval and an evidence-only LangGraph answer. They do not establish successful local LLM generation, cloud model quality, live logistics/market connectivity or a healthy Grafana installation. Those require configured services.

To reproduce, install Playwright in a development Node environment and run `node scripts/capture_workspace.cjs` with the app running on localhost:8501. Set `PLAYWRIGHT_MODULE` if the package is located outside normal Node resolution. `CORTEX_URL` can target another local test instance. Never run this capture with production/customer data.
