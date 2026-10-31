# Cortex deployment privacy notice

Version: 31 October 2026. This describes the implemented software behavior. The deploying organization must supply its legal identity, contact address, processing purposes, lawful basis where applicable, retention schedule, regional hosting details and customer agreements before public deployment. This template is not a legal certification.

## Information stored

The application stores account email, a salted password hash, uploaded source bytes, parsed records/document text, retrieval chunks and optional vectors, chat messages, feedback, lifecycle events and operational run metadata. Files may contain personal or confidential information; upload only information you have authority to process. Account email is used for login, not marketing or AI prompts.

Private workspace content is held in the server's SQLite database by default. Application access is scoped by account ID. Operators with filesystem/database access can access stored information; this is not end-to-end encryption. The software does not supply disk encryption, an automatic retention policy, legal-consent management or backup deletion.

## AI processing

**Evidence-only mode:** no inference provider is called.

**Local model mode:** full relevant document excerpts and recent conversation history may be sent to the configured internal Ollama endpoint. Local vectors are generated with an already-provisioned model on the server. The endpoint policy limits hosts to loopback or named internal services; operators must secure DNS, internal networks, model hosts, logs and backups. Local processing does not waive confidentiality or data-protection obligations.

**Cloud model mode:** enabled only for aggregate analytics explanations. The payload contains approved finite numeric metric fields plus a fixed instruction. Customer names, addresses, bank details, identifiers, labels, uploaded documents, arbitrary questions and chat history are not included. Groups below 10 records or 5 customers are blocked. This is data minimization, not a guarantee against all inference or reidentification. Cloud document RAG is disabled because automatic redaction alone cannot reliably remove every sensitive name/address from arbitrary text. A cloud provider may retain request metadata under its own agreement; the operator must review and disclose those terms.

## Telemetry and integrations

Streamlit usage statistics are disabled by configuration. The new workflow disables legacy LangSmith auto-tracing. Optional Langfuse receives only anonymous run IDs, route, status and duration; raw prompts, responses, document contents, account emails and customer details are not attached. Prometheus/Grafana receive operational aggregates, not customer-level labels. Hosting/platform/network logs outside this application remain the operator's responsibility.

RouteMind reads are administrator-only and use configured server endpoints. Only numeric route metrics are displayed from plan responses; full upstream addresses and names are not sent to AI. Market gateway values are displayed with source timestamps. Operators must authorize and secure each connected application; no third-party connection is enabled by default. The application does not sell data or send marketing email.

## Access, deletion and retention

### Connected modules

Stripe-hosted checkout/portal collects payment information directly; Cortex stores opaque Stripe references and subscription status, not card/bank details. Signed event IDs and billing records are retained separately from workspace content, and workspace erasure does not cancel a subscription. Users manage cancellation in Stripe's portal; the operator must define billing-record retention and account deletion procedures.

An explicitly confirmed Snowflake export sends all selected dataset columns to the operator-configured warehouse. This is a separate external data transfer, not cloud AI inference consent. Importing warehouse rows creates a local source. Local ClamAV receives full file bytes over the approved loopback/internal connection; no third-party public malware-upload API is used. Uploaded file bytes temporarily exist in server memory before scanning; only accepted sources enter active workspace storage. Generated part archives stay in that private browser session until cleared/expired. Logistics assignments and cached numeric snapshots are scoped to the account. DeepEval citation checking is local and telemetry-disabled; Langfuse remains metadata-only.

Users can inspect/export approved analytics records and delete source datasets/indexes. Deleting a dataset does not retroactively delete prior chat excerpts. **Erase workspace content** removes active datasets, chunks, messages, feedback, run and audit rows while retaining the login account. SQLite free pages, backups, exports, screenshots and external provider records are not securely erased by that action. Account deletion and data-subject requests currently require the deploying operator; provide a real contact channel before launch. Agree on retention and backup expiry with the operator.

## Security and limitations

Passwords use PBKDF2-HMAC-SHA256 and random salts. Login attempts are rate-limited per account; server sessions expire after eight hours. Signup currently does not verify email and there is no password reset, SSO or MFA. TLS, encrypted disks/backups, organization roles, gateway rate limiting, malware scanning, independent security review and breach-response procedures are deployment prerequisites. Do not describe this release as GDPR/SOC 2 certified or fully production hardened.
