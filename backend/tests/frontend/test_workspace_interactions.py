"""Exercise stored results and malformed state through real Streamlit reruns."""
from pathlib import Path

import pytest

pytest.skip(
    "The Streamlit frontend was retired; browser coverage now belongs to the React workspace.",
    allow_module_level=True,
)

from streamlit.testing.v1 import AppTest

from frontend.core.navigation import NavigationIntent


APP = str(Path(__file__).resolve().parents[3] / "sdm_local_v2.py")


def test_nl2sql_edit_invalidates_display_and_converter_handoff():
    app = AppTest.from_file(APP, default_timeout=15)
    app.query_params["page"] = "nl2sql"
    app.run()
    app.text_area(key="nl_input_text").set_value("show all users")
    app.button(key="nl_generate").click().run()
    assert not app.exception
    assert app.session_state["nl_last_vm"].success
    assert any(button.key == "nl_to_convert" for button in app.button)
    app.text_area(key="nl_input_text").set_value("show all orders").run()
    assert not app.exception
    assert app.session_state["nl_last_vm"] is None
    assert not any(button.key == "nl_to_convert" for button in app.button)


def test_diff_defaults_and_multistatement_rejection():
    app = AppTest.from_file(APP, default_timeout=15)
    app.query_params["page"] = "diff"
    app.run()
    assert app.selectbox(key="diff_src_dialect").value == "postgres"
    assert app.selectbox(key="diff_tgt_dialect").value == "mysql"
    app.text_area(key="diff_src_sql").set_value("SELECT 1; DROP TABLE users")
    app.text_area(key="diff_tgt_sql").set_value("SELECT 1")
    app.button(key="diff_compare").click().run()
    assert not app.exception
    assert app.error
    assert app.session_state["diff_last_vm"] is None


def test_history_error_filter_has_real_failed_conversions():
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.text_area(key="convert_src_sql").set_value("DROP TABLE users; SELECT 1")
    app.button(key="convert_btn").click().run()
    assert not app.exception
    app.button(key="nav_history").click().run()
    app.selectbox(key="hist_filter").select("Error").run()
    assert not app.exception
    assert len(app.expander) == 1
    assert app.error


def test_invalid_navigation_dialect_is_discarded_without_crashing_widgets():
    app = AppTest.from_file(APP, default_timeout=15)
    app.session_state["sdm_navigation_intent"] = NavigationIntent(
        target_page="convert", action="open_conversion",
        payload={"sql": "SELECT 1", "dialect": "unknown-dialect"},
    )
    app.run()
    assert not app.exception
    assert not app.session_state["sdm_navigation_intent"]


def test_palette_template_navigation_remains_valid_after_payload_validation():
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.button(key="cmd_palette_trigger").click().run()
    app.button(key="cmd_open_templates").click().run()
    assert not app.exception
    assert app.query_params["page"] == ["templates"]
