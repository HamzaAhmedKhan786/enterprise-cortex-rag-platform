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
    for page in ["Reports", "Data studio", "Knowledge", "AI copilot", "Operations", "Integrations", "Governance"]:
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
