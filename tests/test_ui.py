import time

from streamlit.testing.v1 import AppTest

from cortex import data, store


def test_signup_dashboard_pages_and_logout(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_DB", str(tmp_path / "ui.sqlite3"))
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60).run()
    assert not app.exception
    inputs = {widget.label: widget for widget in app.text_input}
    inputs["Work email"].set_value("ui@example.test")
    inputs["Create password"].set_value("ui-strong-password-123")
    inputs["Confirm password"].set_value("ui-strong-password-123")
    app.checkbox[0].check()
    next(button for button in app.button if button.label == "Create workspace").click().run()
    assert not app.exception
    owner = app.session_state["user"]["id"]
    data.seed_demo(owner)
    app.run()
    assert not app.exception
    assert len(app.metric) == 5
    assert app.metric[1].value == "540"
    # Dataset remains scoped, filters recalculate underlying metrics.
    app.multiselect[0].set_value(["Studio Laptop"]).run()
    assert not app.exception
    assert int(app.metric[1].value.replace(",", "")) < 540
    next(button for button in app.sidebar.button if button.label == "Private workspace").click().run()
    assert app.sidebar.radio[0].value == "Security" and not app.exception
    app.checkbox[0].check()
    next(button for button in app.button if button.label == "Save data controls").click().run()
    assert store.preferences(owner)["cloud_aggregates"] is True
    app.sidebar.radio[0].set_value("Snowflake migration").run()
    assert not any(button.label == "Export to a new table" for button in app.button)
    monkeypatch.setenv("CORTEX_ADMIN_USER_ID", owner)
    for page in ["Reports", "Data studio", "Knowledge", "AI copilot", "Subscriptions", "Security", "Snowflake migration", "Live logistics", "Operations", "Integrations", "Governance"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
    next(button for button in app.button if button.label == "Sign out").click().run()
    assert app.title[0].value == "Your intelligence workspace"
    assert not app.exception


def test_session_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_DB", str(tmp_path / "expiry.sqlite3"))
    store.initialize()
    user = store.signup("expired@example.test", "a-long-expired-password")
    user["issued"] = time.time() - 9 * 3600
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=60)
    app.session_state["user"] = user
    app.run()
    assert not app.exception
    assert app.title[0].value == "Your intelligence workspace"


def test_profile_and_admin_sidebar_end_to_end(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from cortex import identity
    monkeypatch.setenv('CORTEX_DB',str(tmp_path/'account-ui.sqlite3'))
    store.initialize()
    user=store.signup('profile-ui@example.test','profile-ui-password-123')
    store.signup('directory-ui@example.test','directory-ui-password-123')
    monkeypatch.setenv('CORTEX_ADMIN_USER_ID',user['id'])
    app=AppTest.from_file('app/streamlit_app.py',default_timeout=60)
    app.session_state['user']=user
    app.run()
    app.sidebar.radio[0].set_value('My Profile').run()
    assert not app.exception
    inputs={w.label:w for w in app.text_input}
    inputs['Full name'].set_value('Profile Analyst')
    inputs['Company / organization name'].set_value('Example Company')
    next(b for b in app.button if b.label=='Save profile').click().run()
    assert identity.profile(user['id'])['full_name']=='Profile Analyst'
    app.sidebar.radio[0].set_value('Admin Dashboard').run()
    assert not app.exception and not app.dataframe
    next(w for w in app.text_input if w.label=='Verify your account password').set_value('profile-ui-password-123')
    next(b for b in app.button if b.label=='Verify for ten minutes').click().run()
    assert not app.exception and app.metric[0].value=='2'
    app.sidebar.radio[0].set_value('Organization').run()
    assert not app.exception
    next(w for w in app.text_input if w.label=='Organization name').set_value('UI Organization')
    next(b for b in app.button if b.label=='Create organization').click().run()
    assert not app.exception
    from cortex import organizations
    assert organizations.list_for(user['id'])[0]['name']=='UI Organization'
    app.sidebar.radio[0].set_value('Team Members').run()
    assert not app.exception
    next(w for w in app.text_input if w.label=='Team name').set_value('UI Team')
    next(b for b in app.button if b.label=='Save team').click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value('Account Settings').run()
    assert not app.exception
    app.sidebar.radio[0].set_value('My Profile').run()
    assert not app.exception
    assert app.query_params['section']==['My Profile']
