"""Workspace modules. Secrets are operator environment settings, never browser inputs."""
import importlib.util
import os
import time

import pandas as pd
import streamlit as st

from cortex import billing, logistics, observability, security, store
from cortex.module_agents import LogisticsAgent, MigrationAgent, ObservabilityAgent, SecurityAgent, SubscriptionAgent


def _error(exc):
    st.error(str(exc) if isinstance(exc, ValueError) else "Service unavailable or request rejected. Check server configuration; secrets and raw provider errors are withheld.")


def subscriptions(owner):
    st.title("Subscriptions & billing")
    st.write("Stripe-hosted checkout and self-service subscription management. Cortex never collects card or bank details.")
    current = billing.account(owner)
    a, b = st.columns(2)
    a.metric("Current plan", current["plan"].title())
    b.metric("Subscription status", current["status"])
    st.caption("A success-page redirect does not activate a subscription. Signed webhooks or a verified Stripe refresh reconcile its status. Existing workspace limits remain unchanged in this release; paid usage quotas are not advertised.")
    configured = bool(os.getenv("STRIPE_SECRET_KEY")) and bool(importlib.util.find_spec("stripe"))
    if not configured:
        st.info("Configure STRIPE_SECRET_KEY (test mode), plan price IDs and STRIPE_WEBHOOK_SECRET to connect billing.")
    agent = SubscriptionAgent()
    for name in ("starter", "team"):
        with st.container(border=True):
            st.subheader(name.title())
            st.caption("The exact recurring amount, currency and terms are displayed by Stripe before you confirm payment.")
            if st.button("Open " + name.title() + " checkout", disabled=not configured or not billing.prices()[name], key="checkout_" + name):
                try:
                    result = agent.run(owner, "checkout", plan=name)
                    st.link_button("Continue to Stripe " + ("test checkout" if result["test_mode"] else "checkout"), result["url"])
                except Exception as exc:
                    _error(exc)
    a, b = st.columns(2)
    if a.button("Open billing portal", disabled=not configured or not current.get("customer")):
        try:
            result = agent.run(owner, "portal")
            st.link_button("Manage subscription securely at Stripe", result["url"])
        except Exception as exc:
            _error(exc)
    if b.button("Refresh subscription status", disabled=not configured or not current.get("customer")):
        try:
            agent.run(owner, "refresh")
            st.rerun()
        except Exception as exc:
            _error(exc)


def security_page(owner):
    st.title("Security & privacy controls")
    st.write("Private workspace and cloud-content blocking are active safeguards. They were status labels, not inaccessible modules; you can now inspect and manage their controls here.")
    st.dataframe(pd.DataFrame(security.posture(owner)), width="stretch", hide_index=True)
    if st.button("Run security agent assessment"):
        SecurityAgent().run(owner, "posture")
        st.success("Assessment recorded in Operations. This is a configuration assessment, not a penetration test.")
    with st.form("privacy_settings"):
        enabled = st.checkbox("Enable aggregate-only cloud explanations for this workspace", value=store.preferences(owner)["cloud_aggregates"])
        st.caption("This never permits raw documents, prompts, names, addresses, bank details or identifiers to leave for cloud AI. Small-cohort restrictions still apply. Billing and warehouse transfers use their separate explicit workflows.")
        if st.form_submit_button("Save data controls", type="primary"):
            SecurityAgent().run(owner, "preferences", cloud_aggregates=enabled)
            st.success("Data controls saved.")
    st.subheader("Change password")
    with st.form("password_change"):
        old = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Change password and revoke older sessions")
    if submitted:
        try:
            if new != confirm:
                raise ValueError("New passwords do not match.")
            store.change_password(owner, old, new)
            st.session_state["user"]["issued"] = time.time()
            st.success("Password changed. Older sessions will be rejected on their next request.")
        except Exception as exc:
            _error(exc)
    st.caption(f"Immutable account ID: {owner}. Administrative rights are assigned by CORTEX_ADMIN_USER_ID, never by signup email.")


def snowflake_page(owner):
    st.title("Snowflake · bidirectional migration")
    st.write("Move a structured workspace dataset to a new Snowflake table, or import an allowlisted Snowflake table. No arbitrary SQL, overwrites or AI-selected migrations.")
    admin = bool(os.getenv("CORTEX_ADMIN_USER_ID")) and owner == os.getenv("CORTEX_ADMIN_USER_ID")
    if not admin:
        st.info("Migration uses shared operator credentials and is restricted to the assigned administrator. Configure your immutable account ID on the server; this is not an email-based permission.")
        return
    agent = MigrationAgent()
    if st.button("Verify Snowflake connection"):
        try:
            st.json(agent.run(owner, "check"))
        except Exception as exc:
            _error(exc)
    export, incoming, history = st.tabs(["Workspace → Snowflake", "Snowflake → workspace", "Migration history"])
    with export:
        tables = {d["id"]: d["name"] for d in store.datasets(owner) if d["kind"] == "table"}
        if not tables:
            st.info("Upload structured data first.")
        else:
            with st.form("snowflake_export"):
                did = st.selectbox("Source workspace dataset", tables, format_func=tables.get)
                confirm = st.checkbox("I authorize transferring all columns, including any personal data, to the configured Snowflake warehouse.")
                submit = st.form_submit_button("Export to a new table", disabled=not tables)
            if submit:
                try:
                    st.json(agent.run(owner, "export", dataset_id=did, confirmed=confirm))
                except Exception as exc:
                    _error(exc)
    with incoming:
        with st.form("snowflake_import"):
            table = st.text_input("Allowlisted source table")
            confirm = st.checkbox("I authorize storing this source table in my local workspace.")
            submit = st.form_submit_button("Import table")
        if submit:
            try:
                st.json(agent.run(owner, "import", table=table, confirmed=confirm))
            except Exception as exc:
                _error(exc)
        st.caption("Limits: 50,000 rows, 100 columns and 10 MiB. Set SNOWFLAKE_ALLOWED_TABLES or import your own completed exports. No silent truncation.")
    with history:
        with store.connection() as db:
            rows = [dict(r) for r in db.execute("SELECT id,direction,destination,status,rows,created FROM migrations WHERE owner=? ORDER BY created DESC", (owner,))]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def logistics_page(owner):
    st.title("Live logistics · RouteMind")
    st.write("Refresh assigned RouteMind delivery plans or poll every 30 seconds while this page is open. A fresh API response is not proof of live GPS; the upstream plan may use simulated traffic or locations.")
    admin = bool(os.getenv("CORTEX_ADMIN_USER_ID")) and owner == os.getenv("CORTEX_ADMIN_USER_ID")
    if admin:
        with st.expander("Assign a plan to a workspace"):
            with st.form("plan_assignment"):
                target = st.text_input("Target immutable account ID", value=owner)
                plan = st.text_input("Existing RouteMind plan ID")
                submitted = st.form_submit_button("Assign read access")
            if submitted:
                try:
                    LogisticsAgent().run(owner, "assign", target_owner=target, plan_id=plan)
                    st.success("Plan assigned.")
                except Exception as exc:
                    _error(exc)
    choices = [row["plan_id"] for row in logistics.links(owner)]
    if not choices:
        st.info("No plans assigned. Ask the operator to configure LOGISTICS_BASE_URL and assign your RouteMind plan ID. Cortex cannot discover shipment IDs from a repository URL alone.")
        return
    selected = st.selectbox("Assigned plan", choices)
    automatic = st.checkbox("Auto-refresh every 30 seconds", value=False)
    @st.fragment(run_every=30 if automatic else None)
    def live_panel():
        refresh = st.button("Refresh live plan")
        if automatic or refresh:
            try:
                LogisticsAgent().run(owner, "fetch", plan_id=selected)
            except Exception as exc:
                _error(exc)
        item = next(r for r in logistics.links(owner) if r["plan_id"] == selected)
        if not item["fetched"]:
            st.info("No snapshot yet; refresh to fetch the plan.")
            return
        age = int(time.time() - item["fetched"])
        st.caption(f"Last successful fetch: {age} seconds ago")
        if age > 90:
            st.warning("Cached snapshot is stale; no current source response has been verified.")
        snapshot = item["snapshot"]
        st.info(snapshot["notice"])
        st.dataframe(pd.DataFrame(snapshot["routes"]), width="stretch", hide_index=True)
    live_panel()


def observability_controls(owner):
    st.subheader("Langfuse & DeepEval activation")
    st.dataframe(pd.DataFrame(observability.readiness(owner)), width="stretch", hide_index=True)
    a, b = st.columns(2)
    if a.button("Verify Langfuse authentication"):
        try:
            st.json(ObservabilityAgent().run(owner, "verify_langfuse"))
        except Exception as exc:
            _error(exc)
    if b.button("Run DeepEval local citation test"):
        try:
            st.json(ObservabilityAgent().run(owner, "evaluate"))
        except Exception as exc:
            _error(exc)
    st.caption("DeepEval runs locally without an LLM judge or telemetry. Langfuse requires its own running server/project keys; installing an SDK does not create that service. Only run metadata is traced.")


def render_module(page, owner):
    {"Subscriptions": subscriptions, "Security": security_page, "Snowflake migration": snowflake_page, "Live logistics": logistics_page}[page](owner)
