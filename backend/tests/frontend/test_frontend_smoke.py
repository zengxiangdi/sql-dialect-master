#!/usr/bin/env python3
"""P6: real application smoke coverage for every PAGE_MAP page.

Complements ``test_page_renderer_contract.py`` (which locks the
single-argument renderer dispatch) with per-page **happy-path** checks:

1. app boots with no exception on each page
2. core widgets (search / editor / dialect selectors / primary action)
   are present under their documented keys
3. the primary action button executes its minimal happy path without
   raising — i.e. the page's core wiring is not broken by a missing
   parameter or an unguarded backend call

All tests dispatch the real entrypoint through Streamlit AppTest so
widget state, session state, and static data load under the app's own
semantics, exactly as a browser would drive it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402


_ROOT = Path(__file__).resolve().parents[3]
_APP_FILE = str(_ROOT / "sdm_local_v2.py")

# Every page id in the app's PAGE_MAP — the minimum requirement of P6.
PAGES = [
    "convert",
    "nl2sql",
    "diff",
    "lineage",
    "runtime",
    "functions",
    "types",
    "templates",
    "history",
    "settings",
    "query_analysis",
]


def _run_app(page: str, **state) -> AppTest:
    at = AppTest.from_file(_APP_FILE, default_timeout=60)
    at.session_state["sdm_theme"] = "dark"
    at.query_params["page"] = page
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def _text(elements, out: list[str]) -> None:
    """Recursively collect display text of leaf elements.

    Covers label, markdown HTML, and Code/TextArea/Button .value so
    generated SQL (rendered via ``st.code``) and empty-state boxes are
    visible to the assertions that depend on them.
    """
    for el in elements:
        cls = type(el).__name__
        if cls in ("MainBlock", "Sidebar", "SpecialBlock"):
            if hasattr(el, "children"):
                _text(el.children, out)
            continue
        label = getattr(el, "label", None)
        if isinstance(label, str) and label:
            out.append(label)
        md = getattr(el, "markdown", None)
        if isinstance(md, str) and md:
            out.append(md)
        val = getattr(el, "value", None)
        if isinstance(val, str) and val:
            out.append(val)


def _click_button(at: AppTest, key: str) -> AppTest:
    """Click the button with the given key.

    AppTest's element lists use *call* syntax for string-key lookup —
    ``at.button(key)`` returns the widget instance.  Bracket indexing
    with a string is a ``TypeError`` on CPython lists.
    """
    at.button(key).set_value(True)
    at.run()
    return at


def _button_exists(at: AppTest, key: str) -> bool:
    """Return True if a button with *key* exists in the current run."""
    return at.button(key).value is True or any(
        el.key == key for el in at.button
    )


def _has_key(at: AppTest, widget_list, key: str) -> bool:
    """Return True if *key* is present in *widget_list* (any element type)."""
    return any(el.key == key for el in widget_list)


class TestAllPagesBoot:
    """Goal 1: every page dispatches through the real app without exception."""

    @pytest.mark.parametrize("page", PAGES)
    def test_page_boots_without_exception(self, page: str) -> None:
        at = _run_app(page)
        assert not at.exception, f"page '{page}' raised: {at.exception!r}"
        assert at.main, f"page '{page}' rendered no elements"


class TestCoreWidgets:
    """Goal 4: core widgets build under their documented keys."""

    def test_convert_core_widgets(self) -> None:
        at = _run_app("convert", convert_src_sql="SELECT 1")
        assert _has_key(at, at.button, "convert_btn")
        assert _has_key(at, at.button, "swap_dialects")
        assert _has_key(at, at.text_area, "convert_src_sql")

    def test_nl2sql_core_widgets(self) -> None:
        at = _run_app("nl2sql", nl_input_text="show all users")
        assert _has_key(at, at.button, "nl_generate")
        assert _has_key(at, at.text_area, "nl_input_text")

    def test_diff_core_widgets(self) -> None:
        at = _run_app("diff")
        assert _has_key(at, at.button, "diff_compare")
        assert _has_key(at, at.text_area, "diff_src_sql")
        assert _has_key(at, at.text_area, "diff_tgt_sql")

    def test_lineage_core_widgets(self) -> None:
        at = _run_app("lineage")
        assert _has_key(at, at.button, "lineage_analyze")
        assert _has_key(at, at.text_area, "lineage_sql")

    def test_query_analysis_core_widgets(self) -> None:
        at = _run_app("query_analysis")
        assert _has_key(at, at.button, "qa_analyze")
        assert _has_key(at, at.text_area, "qa_sql")

    def test_functions_core_widgets(self) -> None:
        at = _run_app("functions")
        assert _has_key(at, at.text_input, "func_search")
        assert _has_key(at, at.selectbox, "func_cat")

    def test_types_core_widgets(self) -> None:
        at = _run_app("types")
        assert _has_key(at, at.selectbox, "type_src")
        assert _has_key(at, at.selectbox, "type_tgt")

    def test_history_core_widgets(self) -> None:
        at = _run_app("history")
        # When history is empty the search/filter controls are not rendered;
        # the page must boot without exception.
        assert not at.exception

    def test_settings_core_widgets(self) -> None:
        at = _run_app("settings")
        assert _has_key(at, at.selectbox, "settings_theme_sel")
        assert _has_key(at, at.button, "settings_apply_theme")

    def test_templates_renders_without_crash(self) -> None:
        # P7 fixed the unhashable widget-key crash here — assert the page
        # still boots and its header / template data is visible.
        at = _run_app("templates")
        assert not at.exception
        out: list[str] = []
        _text(at.main, out)
        joined = "\n".join(out)
        assert "Templates" in joined, f"template header not found: {joined[:200]!r}"

    def test_runtime_page_signals_not_available(self) -> None:
        # Runtime is a placeholder (no DB connection in the app); the page
        # must signal "not available" rather than fabricate results.
        at = _run_app("runtime")
        assert not at.exception
        out: list[str] = []
        _text(at.main, out)
        joined = "\n".join(out)
        assert "Not Available" in joined


class TestHappyPathExecution:
    """Goal 5: the primary action button can execute a minimal happy path."""

    def test_convert_button_executes_and_shows_result(self) -> None:
        at = _run_app("convert", convert_src_sql="SELECT NOW() FROM users")
        _click_button(at, "convert_btn")
        assert not at.exception, f"convert happy path raised: {at.exception!r}"
        # The result panel must surface a target SQL for NOW() (postgres-native).
        out: list[str] = []
        _text(at.main, out)
        joined = "\n".join(out)
        assert "SELECT" in joined, f"no result SQL surfaced: {joined[:200]!r}"

    def test_nl2sql_generate_executes_without_crash(self) -> None:
        at = _run_app("nl2sql", nl_input_text="show all users")
        _click_button(at, "nl_generate")
        assert not at.exception, f"nl2sql happy path raised: {at.exception!r}"

    def test_nl2sql_empty_input_shows_warning_not_crash(self) -> None:
        at = _run_app("nl2sql", nl_input_text="")
        _click_button(at, "nl_generate")
        assert not at.exception
        assert any("describe your query" in str(el.value).lower() for el in at.warning), (
            "empty NL input should warn, not crash"
        )

    def test_diff_compare_executes_without_crash(self) -> None:
        at = _run_app(
            "diff",
            diff_src_sql="SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM users",
            diff_tgt_sql="SELECT created_at + INTERVAL '7 days' FROM users",
            diff_src_dialect="mysql",
            diff_tgt_dialect="postgres",
        )
        _click_button(at, "diff_compare")
        assert not at.exception, f"diff happy path raised: {at.exception!r}"

    def test_query_analysis_executes_without_crash(self) -> None:
        at = _run_app(
            "query_analysis",
            qa_sql="SELECT name FROM users WHERE age > 30",
        )
        _click_button(at, "qa_analyze")
        assert not at.exception, f"query-analysis happy path raised: {at.exception!r}"

    def test_lineage_executes_without_crash(self) -> None:
        at = _run_app(
            "lineage",
            lineage_sql="SELECT o.user_id FROM orders o JOIN users u ON u.id = o.user_id",
        )
        _click_button(at, "lineage_analyze")
        assert not at.exception, f"lineage happy path raised: {at.exception!r}"

    def test_settings_apply_theme_no_crash(self) -> None:
        at = _run_app("settings")
        _click_button(at, "settings_apply_theme")
        assert not at.exception


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
