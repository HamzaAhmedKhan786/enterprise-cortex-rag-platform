"""Cortex: local-first, tenant-scoped business intelligence."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env')
from cortex import data, store
from cortex.retrieval import STRATEGIES, build_index, evaluate_retrieval, search

st.set_page_config(page_title='Cortex · Intelligence workspace', page_icon=':material/hub:', layout='wide')
store.initialize()
st.markdown('''<style>
.stApp{background:#f4f7f8;color:#17353e}[data-testid="stSidebar"]{background:#102e36;color:#d8e9e8}[data-testid="stSidebar"] *{color:inherit}.block-container{padding-top:2rem;max-width:1560px}h1,h2,h3{color:#17353e;letter-spacing:-.04em}h1{font-size:2.4rem!important}h2{font-size:1.4rem!important}[data-testid="stMetric"]{background:white;border:1px solid #e0e9eb;border-radius:14px;padding:20px}[data-testid="stMetricLabel"]{color:#6a8088;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}[data-testid="stMetricValue"]{font-size:1.9rem;font-weight:650}[data-testid="stForm"],[data-testid="stExpander"]{background:white;border:1px solid #e0e9eb;border-radius:14px}.hero{background:linear-gradient(115deg,#102e36,#155d5a);border-radius:18px;padding:30px 34px;color:white;margin:0 0 25px}.hero h1,.hero p{color:white}.hero h1{margin:8px 0}.hero p{opacity:.78;max-width:850px}.eyebrow{font-size:.7rem;letter-spacing:.18em;color:#91dbc8}.badge{display:inline-block;font-size:.72rem;border:1px solid #74c5b777;border-radius:20px;padding:5px 12px;color:#bde9de}.wordmark{display:flex;gap:12px;align-items:center;font-size:1.7rem;font-weight:700;letter-spacing:-.05em}.wordmark svg{width:36px;height:36px}[data-testid="stSidebar"] button,[data-testid="stSidebar"] button *{color:#17353e}.stButton>button{border-radius:9px}.stButton>button[kind="primary"]{background:#087f76;border-color:#087f76}footer{visibility:hidden}@media(max-width:800px){.block-container{padding:1rem;padding-top:4.5rem}.hero{padding:20px}.hero h1{font-size:1.7rem!important}[data-testid="stMetric"]{padding:12px}[data-testid="stMetricValue"]{font-size:1.5rem}}
</style>''', unsafe_allow_html=True)
LOGO = '<div class="wordmark"><svg viewBox="0 0 40 40" fill="none" aria-hidden="true"><path d="M20 3 36 12v16L20 37 4 28V12Z" stroke="#77d6c1" stroke-width="2"/><path d="m12 15 8-5 8 5v10l-8 5-8-5Z" stroke="#77d6c1" stroke-width="2"/><path d="m4 12 16 9 16-9M20 21v16" stroke="#77d6c1" stroke-width="2"/></svg>Cortex</div>'

def hero(kicker, title, description):
    # Application-owned strings only; customer content never enters unsafe HTML.
    st.markdown(f'<div class="hero"><div class="eyebrow">{kicker}</div><h1>{title}</h1><p>{description}</p><span class="badge">Local-first · Evidence-led · Workspace isolated</span></div>', unsafe_allow_html=True)

def error_notice(error):
    st.error(str(error) if isinstance(error, ValueError) else 'Operation could not complete. Check the configured service or optional dependency. Raw service errors are withheld to protect credentials and customer data.')

def authenticate():
    user = st.session_state.get('user')
    if store.session_valid(user):
        return user
    if user:
        st.session_state.clear()
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        st.markdown(LOGO, unsafe_allow_html=True)
        st.caption('YOUR DATA. CLEARER DECISIONS.')
        st.title('Your intelligence workspace')
        st.write('Connect business records and company knowledge. Make decisions with traceable numbers and evidence.')
        signin, signup = st.tabs(['Sign in', 'Create account'])
        with signin:
            with st.form('signin'):
                email = st.text_input('Email')
                password = st.text_input('Password', type='password')
                submit = st.form_submit_button('Sign in', type='primary', width='stretch')
            if submit:
                try:
                    st.session_state.user = store.login(email, password)
                    st.rerun()
                except Exception as error:
                    error_notice(error)
        with signup:
            with st.form('signup'):
                email = st.text_input('Work email')
                password = st.text_input('Create password', type='password', help='12–256 characters')
                confirm = st.text_input('Confirm password', type='password')
                accepted = st.checkbox('I have read the privacy notice and am authorized to upload this data.')
                submit = st.form_submit_button('Create workspace', type='primary', width='stretch')
            if submit:
                try:
                    if not accepted or password != confirm:
                        raise ValueError('Accept the privacy notice and ensure the passwords match.')
                    st.session_state.user = store.signup(email, password)
                    st.rerun()
                except Exception as error:
                    error_notice(error)
        with st.expander('Privacy notice'):
            st.write('Files and chat history are stored on this server, isolated by account. Local inference may process full relevant content. Cloud AI is optional and accepts only approved numeric aggregates. Names, addresses, bank details, questions and raw documents do not go to cloud AI. Administrators control storage and backups.')
            st.caption('Single-node release: no email verification, password recovery, SSO or MFA yet. Read docs/PRIVACY_POLICY.md before deployment.')
    st.stop()

user = authenticate()
owner = user['id']
with st.sidebar:
    st.markdown(LOGO, unsafe_allow_html=True)
    st.caption('INTELLIGENCE, WITH EVIDENCE')
    st.divider()
    page = st.radio('Workspace', ['Overview', 'Reports', 'Data studio', 'Knowledge', 'AI copilot', 'Subscriptions', 'Security', 'Snowflake migration', 'Live logistics', 'Operations', 'Integrations', 'Governance'], label_visibility='collapsed', key='workspace_page', format_func=lambda name: 'Carol · AI copilot' if name == 'AI copilot' else name)
    st.divider()
    st.button('Private workspace', key='private_controls', on_click=lambda: st.session_state.update(workspace_page='Security'), width='stretch')
    st.write('Local data boundary')
    st.button('AI data controls', key='cloud_controls', on_click=lambda: st.session_state.update(workspace_page='Security'), width='stretch')
    st.caption('Raw-content egress stays blocked by policy')
    if st.button('Sign out', icon=':material/logout:', width='stretch'):
        st.session_state.clear()
        st.rerun()

def select_analytics():
    tables = [d for d in store.datasets(owner) if d['kind'] == 'table' and d['profile'].get('analytics_ready')]
    if not tables:
        st.info('Your workspace is empty. Upload records in Data studio or load synthetic demonstration data.')
        if st.button('Load demonstration workspace', type='primary', icon=':material/science:'):
            data.seed_demo(owner)
            st.rerun()
        st.stop()
    names = {d['id']: d['name'] for d in tables}
    selected = st.selectbox('Analytics dataset', names, format_func=names.get)
    item = store.dataset(owner, selected)
    frame, rejected = data.validate_records(item['payload']['rows'])
    if frame.empty:
        st.warning('No valid dates and revenue rows. Correct the source in Data studio.')
        st.stop()
    if item['name'].startswith('demo-'):
        st.caption('DEMONSTRATION DATA · Synthetic commerce records, not PostgreSQL records or live shipments.')
    a, b, c = st.columns(3)
    dates = a.date_input('Date range', (frame.date.min().date(), frame.date.max().date()), key=f'dates_{selected}')
    products = b.multiselect('Products', sorted(frame['product'].unique()), placeholder='All products', key=f'products_{selected}')
    customers = c.multiselect('Customer references', sorted(frame.customer_id.unique()), placeholder='All customers', key=f'customers_{selected}')
    if len(dates) != 2:
        st.info('Choose a start and end date.')
        st.stop()
    filtered = data.filter_records(frame, dates[0], dates[1], products, customers)
    st.caption(f'{len(filtered):,} of {len(frame):,} valid records · {rejected} invalid rows excluded · Inclusive dates · Financial values must use EUR')
    return filtered, selected

def chart(value, key):
    st.altair_chart(value.configure_view(strokeWidth=0).configure_axis(labelColor='#6b818a', titleColor='#48616a', gridColor='#e6edef').configure_legend(labelColor='#48616a'), width='stretch', key=key)

if page in {'Overview', 'Reports'}:
    hero('BUSINESS INTELLIGENCE', 'A clearer view of your business.', 'Understand performance, investigate the signals, and act on traceable evidence. Every number follows your selected dataset and filters.')
    frame, selected = select_analytics()
    m = data.metrics(frame)
    values = [('Recorded revenue', f"€{m['revenue']:,.0f}"), ('Record count', f"{m['records']:,}"), ('Customers', m['customers']), ('Avg. record value', f"€{m['average_record_value']:,.0f}"), ('On-time delivery', f"{m['on_time_pct']:.1f}%" if 'on_time_pct' in m else 'Unavailable')]
    for col, (label, value) in zip(st.columns(5), values):
        col.metric(label, value)
    if frame.empty:
        st.info('No records match these filters.')
        st.stop()
    if page == 'Overview':
        left, right = st.columns([1.5, 1])
        with left:
            st.subheader('Revenue over time')
            trend = frame.assign(week=frame.date.dt.to_period('W').dt.start_time).groupby('week', as_index=False).revenue.sum()
            chart(alt.Chart(trend).mark_area(line=True, color='#087f7644').encode(x=alt.X('week:T', title=None), y=alt.Y('revenue:Q', title='Revenue (€)'), tooltip=['week:T', alt.Tooltip('revenue:Q', format=',.2f')]).properties(height=260), 'trend')
        with right:
            st.subheader('Product contribution')
            grouped = frame.groupby('product', as_index=False).revenue.sum()
            chart(alt.Chart(grouped).mark_bar(color='#087f76', cornerRadiusEnd=5).encode(x=alt.X('revenue:Q', title='Revenue (€)'), y=alt.Y('product:N', sort='-x', title=None), tooltip=['product', 'revenue']).properties(height=260), 'products')
        left, right = st.columns(2)
        with left:
            st.subheader('Revenue mix')
            dim = 'category' if 'category' in frame else 'product'
            grouped = frame.groupby(dim, as_index=False).revenue.sum()
            chart(alt.Chart(grouped).mark_arc(innerRadius=70, outerRadius=110, cornerRadius=3).encode(theta='revenue:Q', color=alt.Color(f'{dim}:N', scale=alt.Scale(range=['#087f76', '#43b6a4', '#89d5bc', '#b8d9d0', '#d8ac65'])), tooltip=[dim, 'revenue']).properties(height=270), 'mix')
        with right:
            st.subheader('Customer concentration · top 10')
            grouped = frame.groupby('customer_id', as_index=False).revenue.sum().nlargest(10, 'revenue')
            chart(alt.Chart(grouped).mark_bar(color='#5486a0', cornerRadiusEnd=4).encode(x=alt.X('revenue:Q', title='Revenue (€)'), y=alt.Y('customer_id:N', sort='-x', title=None), tooltip=['customer_id', 'revenue']).properties(height=270), 'customers')
        left, right = st.columns(2)
        with left:
            st.subheader('Weekly purchasing pattern')
            heat = frame.assign(month=frame.date.dt.strftime('%Y-%m'), weekday=frame.date.dt.day_name()).groupby(['month', 'weekday'], as_index=False).revenue.sum()
            chart(alt.Chart(heat).mark_rect(cornerRadius=3).encode(x=alt.X('weekday:N', sort=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'], title=None), y=alt.Y('month:N', title=None), color=alt.Color('revenue:Q', scale=alt.Scale(scheme='tealblues')), tooltip=['month', 'weekday', 'revenue']).properties(height=250), 'heatmap')
        with right:
            st.subheader('Operational distribution')
            dim = 'status' if 'status' in frame else 'product'
            counts = frame.groupby(dim).size().reset_index(name='records')
            chart(alt.Chart(counts).mark_bar(color='#d5a655', cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(x=alt.X(f'{dim}:N', title=None), y='records:Q', tooltip=[dim, 'records']).properties(height=250), 'status')
        left, right = st.columns(2)
        with left:
            st.subheader('Unit economics by product')
            if 'cost' in frame and frame.cost.notna().all():
                group = frame.groupby('product', as_index=False)[['revenue', 'cost']].sum()
                group['contribution'] = group.revenue - group.cost
                chart(alt.Chart(group).mark_circle(size=180, color='#087f76').encode(x=alt.X('revenue:Q', title='Revenue (€)'), y=alt.Y('contribution:Q', title='Contribution (€)'), tooltip=['product', 'revenue', 'contribution']).properties(height=250), 'economics')
            else:
                st.info('Complete cost values are required for contribution analysis.')
        with right:
            st.subheader('Regional performance')
            if 'region' in frame:
                group = frame.groupby('region', as_index=False).revenue.sum()
                chart(alt.Chart(group).mark_bar(color='#6d9d98').encode(x='region:N', y='revenue:Q', tooltip=['region', 'revenue']).properties(height=250), 'regions')
            else:
                st.info('Add region to enable regional analysis.')
        st.subheader('Decision brief')
        st.caption('Deterministic signals and recommended investigations. Rules do not establish causation or execute business changes.')
        for action in data.strategies(frame):
            with st.container(border=True):
                st.markdown(f"**{action['priority']} · {action['signal']}**")
                st.write(action['action'])
                st.caption(f"Evidence: {action['evidence']} · Rule: {action['rule']}")
    else:
        st.subheader('Reports that reconcile')
        dim = st.radio('Group by', ['product', 'customer_id', 'date'] + (['region'] if 'region' in frame else []), horizontal=True)
        report = frame.assign(date=frame.date.dt.normalize()).groupby(dim, as_index=False).agg(records=('revenue','size'), revenue=('revenue','sum'), average_record_value=('revenue','mean'))
        st.dataframe(report.round(2), width='stretch', hide_index=True)
        st.download_button('Export grouped report', data.safe_csv(report), 'cortex-report.csv', 'text/csv', icon=':material/download:')
        st.subheader('Underlying records')
        st.dataframe(frame, width='stretch', hide_index=True)
        st.download_button('Export filtered records', data.safe_csv(frame), 'cortex-records.csv', 'text/csv')
        st.caption('Only approved analytics columns are exported. Spreadsheet formula prefixes are escaped.')
elif page == 'Data studio':
    hero('DATA FOUNDATION', 'Upload once. Build with confidence.', 'Preserve sources, inspect quality, and choose a retrieval strategy. Analytics and document indexes share your workspace boundary.')
    upload, registry = st.tabs(['Upload & profile', 'Dataset registry'])
    with upload:
        left, right = st.columns([1.4, 1])
        with left:
            file = st.file_uploader('Add a raw data file', type=['csv', 'json', 'xlsx', 'txt', 'pdf'], max_upload_size=100, key='raw_upload')
            if file and st.button('Validate and register', type='primary', icon=':material/upload_file:'):
                try:
                    from cortex.module_agents import UploadAgent
                    result = UploadAgent().run(owner, 'scan_and_register', name=file.name, raw=file.getvalue())
                    st.session_state.upload_archive = {'owner': owner, 'content': result['archive']}
                    st.json(result['manifest'])
                    st.success('File registered. Review the profile in Dataset registry.')
                except Exception as error:
                    error_notice(error)
            st.caption('Up to 100 MiB · ClamAV required · Files at least 10 MiB split into parts up to 9 MiB · 50,000 rows per table part · 200 PDF pages')
            archive = st.session_state.get('upload_archive')
            if archive and archive['owner'] == owner:
                st.download_button('Download scanned parts and manifest', archive['content'], 'scanned-parts.zip', 'application/zip')
        with right:
            st.subheader('A trustworthy foundation')
            st.write('1. Validate and fingerprint the source\n\n2. Profile the bounded dataset\n\n3. Review the recommendation\n\n4. Choose and build an index\n\n5. Test with your questions')
        with st.expander('Analytics schema and sample CSV', expanded=True):
            st.code('date,product,customer_id,revenue,cost,quantity,category,region,status,delivery_days,promised_days\n2026-10-01,Studio Laptop,C-001,1249,900,1,Computing,Berlin,Delivered,3,5', language='text')
            st.write('Required: date, product, customer_id, revenue. One row is one business record. Use opaque references, not names. One currency: EUR. Numbers are never inferred by an LLM.')
        if st.button('Add synthetic demonstration data', icon=':material/science:'):
            data.seed_demo(owner)
            st.success('Synthetic records and policies added to this workspace.')
    with registry:
        items = store.datasets(owner)
        if not items:
            st.info('No datasets yet.')
        for item in items:
            with st.expander(f"{item['name']} · {item['kind']} · {item['status']}"):
                st.write(item['profile']['reason'])
                st.json(item['profile'])
                if st.button('Get local AI strategy advice', key=f"advice_{item['id']}"):
                    try:
                        from cortex.recommend import local_recommendation
                        with st.spinner('Reviewing a bounded local sample…'):
                            st.write(local_recommendation(owner, item['id']))
                        st.caption('Local AI advice is provisional. Select and evaluate a supported method yourself.')
                    except Exception as error:
                        error_notice(error)
                st.caption(f"Dataset version: {item['id']}")
                if item['kind'] in {'document', 'table'}:
                    method = st.selectbox('Retrieval configuration', STRATEGIES, format_func=STRATEGIES.get, key=f"method_{item['id']}")
                    st.caption('Hybrid requires cached local MiniLM. Fusion uses RRF; reranking uses lexical coverage, not a neural cross-encoder. Recommendations are heuristics until evaluated.')
                    if st.button('Build selected index', key=f"index_{item['id']}", type='primary'):
                        try:
                            with st.spinner('Building local index…'):
                                count = build_index(owner, item['id'], method)
                            st.success(f'Ready: {count} chunks. Original file unchanged.')
                        except Exception as error:
                            error_notice(error)
                confirm = st.checkbox('Delete this dataset and its index', key=f"confirm_{item['id']}")
                if st.button('Delete dataset', key=f"delete_{item['id']}", disabled=not confirm):
                    store.delete_dataset(owner, item['id'])
                    st.rerun()
elif page == 'Knowledge':
    hero('EVIDENCE EXPLORER', 'Find the source. Test the answer.', 'Inspect retrieved evidence and citations. Test configurations with human-reviewed questions before choosing a winner.')
    docs = [d for d in store.datasets(owner) if d['status'] == 'ready']
    if not docs:
        st.info('Upload a document and build an index in Data studio first.')
    else:
        names = {d['id']: d['name'] for d in docs}
        selected = st.selectbox('Document index', names, format_func=names.get)
        with st.form('search'):
            question = st.text_input('Search your knowledge', placeholder='How long does a refund take?')
            submit = st.form_submit_button('Find evidence', type='primary')
        if submit:
            try:
                hits = search(owner, question, selected)
                if not hits:
                    st.info('No relevant evidence found.')
                for hit in hits:
                    with st.container(border=True):
                        st.write(hit['text'])
                        st.caption(f"{hit['source']} · {hit['citation']} · BM25 {hit['score']} · {hit['strategy']}")
                store.audit(owner, 'knowledge_searched', selected, {'retrieved': len(hits)})
            except Exception as error:
                error_notice(error)
        with st.expander('Evaluate this configuration'):
            st.caption('A single query is a smoke test, not a benchmark.')
            with st.form('eval'):
                question = st.text_input('Test question')
                expected = st.text_input('Expected evidence phrase')
                submit = st.form_submit_button('Run deterministic evidence test')
            if submit:
                try:
                    result = evaluate_retrieval(owner, selected, question, expected)
                    st.json(result)
                    store.audit(owner, 'retrieval_evaluated', selected, result)
                except Exception as error:
                    error_notice(error)
elif page == 'AI copilot':
    hero('CAROL · YOUR AI ASSISTANT', 'Meet Carol. Answers with a paper trail.', 'Evidence-only responses, local generation, or bounded cloud explanations. The orchestrator records its stages; tools own the calculations.')
    from cortex.carol import FAQ
    faq = st.selectbox('Common questions for Carol', ['Choose a common question'] + list(FAQ))
    ask_faq = st.button('Ask Carol', disabled=faq == 'Choose a common question')
    route = st.radio('Assistant focus', ['Documents', 'Analytics'], horizontal=True)
    frame = None
    if route == 'Analytics':
        frame, _ = select_analytics()
    mode = st.selectbox('Inference boundary', ['Evidence only', 'Local Ollama'] + (['Cloud aggregates'] if route == 'Analytics' and store.preferences(owner)['cloud_aggregates'] else []))
    st.caption('Cloud AI receives numeric aggregates only, with at least 10 records and 5 customers. Your question, names, addresses, bank details, labels, history and documents remain local.' if mode == 'Cloud aggregates' else 'Local inference can use full relevant evidence and recent workspace conversation history. Evidence-only mode calls no model.')
    for message in reversed(store.history(owner, 'messages', 12)):
        with st.chat_message('user'):
            st.write(message['question'])
        with st.chat_message('assistant'):
            st.write(message['answer'])
            st.caption(f"Run {message['run_id']}")
    question = st.chat_input('Ask about company knowledge or the selected business metrics…', max_chars=2000)
    if ask_faq:
        question = faq
    if question:
        try:
            from cortex.module_agents import CarolAgent
            with st.spinner('Checking privacy → gathering evidence → preparing response…'):
                result = CarolAgent().run(owner, 'ask', question=question, route='documents' if ask_faq else route.lower(), mode='Evidence only' if ask_faq else mode, frame=frame)
            st.session_state.last_result = {'owner': owner, 'run_id': result['run_id'], 'steps': result['steps'], 'hits': result.get('hits', [])}
            st.rerun()
        except Exception as error:
            error_notice(error)
    result = st.session_state.get('last_result')
    if result and result['owner'] == owner:
        with st.expander('Latest agent steps and evidence'):
            st.dataframe(pd.DataFrame(result['steps']), width='stretch', hide_index=True)
            for hit in result['hits']:
                st.write(hit['text'])
                st.caption(hit['citation'])
        rating = st.radio('Was this answer useful?', ['Helpful', 'Needs improvement'], horizontal=True)
        if st.button('Save feedback'):
            store.feedback(owner, result['run_id'], rating)
            st.success('Feedback recorded.')
elif page == 'Operations':
    hero('OPERATIONS & OBSERVABILITY', 'Follow every decision.', 'Inspect lifecycle events and agent runs. Operational metadata stays separate from prompts and customer content.')
    runs = store.history(owner, 'runs')
    values = [('Recent runs', len(runs)), ('Completed', sum(r['status'] == 'completed' for r in runs)), ('Failed', sum(r['status'] == 'failed' for r in runs)), ('Avg. duration', f"{sum(r['duration'] for r in runs) / max(1, len(runs)):.2f}s")]
    for col, (label, value) in zip(st.columns(4), values):
        col.metric(label, value)
    st.subheader('Run history')
    if runs:
        st.dataframe(pd.DataFrame(runs).drop(columns=['owner']), width='stretch', hide_index=True)
    else:
        st.info('Ask the copilot to create your first tracked run.')
    st.subheader('Workspace audit trail')
    events = store.history(owner, 'events')
    if events:
        st.dataframe(pd.DataFrame(events).drop(columns=['owner']), width='stretch', hide_index=True)
    from app.modules_ui import observability_controls
    observability_controls(owner)
    st.subheader('Other component readiness')
    rows = [{'component': name, 'installed': bool(importlib.util.find_spec(module)), 'role': role} for name, module, role in [('LangGraph','langgraph','Bounded agent workflow'),('LangChain Ollama','langchain_ollama','Local model adapter')]]
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    st.caption('Installed does not mean connected. Prometheus and Grafana use the Docker observability profile. Kafka/RabbitMQ are deferred until durable multi-worker ingestion is needed.')
elif page in {'Subscriptions', 'Security', 'Snowflake migration', 'Live logistics'}:
    from app.modules_ui import render_module
    render_module(page, owner)
elif page == 'Integrations':
    hero('CONNECTED OPERATIONS', 'Bring your systems into view.', 'Read-only adapters for RouteMind and a market-data gateway. Freshness and limitations are explicit; disconnected services never display invented values.')
    st.subheader('RouteMind · Agentic Logistics AI')
    st.link_button('View integration repository', 'https://github.com/HamzaAhmedKhan786/agentic-logistics-ai')
    st.caption('Verified contract: /api/health and /api/plans/{run_id}. Plan data is not carrier shipment tracking or vehicle GPS.')
    st.write('Connection configured' if os.getenv('LOGISTICS_BASE_URL') else 'Not connected · Set LOGISTICS_BASE_URL on the server')
    admin = bool(os.getenv('CORTEX_ADMIN_USER_ID')) and owner == os.getenv('CORTEX_ADMIN_USER_ID')
    if not admin:
        st.info('Live reads are restricted to the configured administrator until upstream tenant authorization is available.')
    else:
        from cortex.integrations import logistics_health, logistics_plan, market_snapshot
        if st.button('Check RouteMind connection'):
            try:
                st.json(logistics_health())
            except Exception as error:
                error_notice(error)
        with st.form('plan'):
            run_id = st.text_input('RouteMind plan ID')
            fetch = st.form_submit_button('Refresh plan snapshot')
        if fetch:
            try:
                result = logistics_plan(run_id)
                st.info(result['notice'])
                st.caption(f"Fetched {result['fetched_at']} · {result['status']}")
                st.dataframe(pd.DataFrame(result['routes']), width='stretch', hide_index=True)
                store.audit(owner, 'logistics_snapshot_read', detail={'routes': len(result['routes'])})
            except Exception as error:
                error_notice(error)
        st.subheader('Market intelligence gateway')
        st.caption('Requires MARKET_BASE_URL. GET /snapshot must return as_of and numeric indicators.')
        if st.button('Fetch market snapshot'):
            try:
                result = market_snapshot()
                st.warning('Source older than 24 hours' if result['stale'] else 'Source timestamp is within 24 hours')
                st.caption(result['as_of'])
                st.dataframe(pd.DataFrame(result['indicators']), width='stretch', hide_index=True)
            except Exception as error:
                error_notice(error)
elif page == 'Governance':
    hero('TRUST & CONTROL', 'Your data boundary is explicit.', 'Understand what is stored, what may leave the server, and how to remove workspace data. Privacy controls are part of the execution path.')
    a, b = st.columns(2)
    with a:
        st.subheader('Local inference')
        st.write('Full relevant document evidence and recent chat history can reach the internal Ollama endpoint. Uploaded sources stay on this server. Local processing still requires authorization and secure hosting.')
    with b:
        st.subheader('Cloud inference')
        st.write('Only allowlisted numeric aggregates. Names, addresses, bank details, labels, questions and documents are excluded. Small cohorts are blocked. Cloud document RAG is disabled.')
    files = {'Privacy policy':'PRIVACY_POLICY.md', 'User guide':'USER_GUIDE.md', 'Architecture':'ARCHITECTURE.md', 'System design':'SYSTEM_DESIGN.md', 'Product requirements':'PRD.md'}
    selected = st.selectbox('Read a document', files)
    path = ROOT / 'docs' / files[selected]
    if path.exists():
        st.markdown(path.read_text(encoding='utf-8'))
    st.divider()
    st.caption(f'Your immutable account ID: {owner}')
    st.subheader('Workspace retention')
    st.caption('Erasure removes active records, chunks, chats, feedback and audit data. Backups, SQLite free pages and external provider records require separate operator handling. Your login account remains.')
    confirm = st.text_input('Type ERASE MY WORKSPACE to remove your data')
    if st.button('Erase workspace content', disabled=confirm != 'ERASE MY WORKSPACE'):
        store.erase_workspace(owner)
        st.session_state.pop('last_result', None)
        st.session_state.pop('upload_archive', None)
        st.session_state.pop('raw_upload', None)
        st.success('Workspace content removed from active storage.')
