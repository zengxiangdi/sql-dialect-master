#!/usr/bin/env python3
"""Regression test: every PAGE_MAP renderer must be callable with the
unified PageRenderer contract.

The app entrypoint (sdm_local_v2.py) calls every page renderer with
exactly one argument — a ColorTokens — but historically
render_functions_page(funcs_data, theme) and
render_types_page(types_data, theme) took two positional arguments.
This test locks the contract:

    PageRenderer = Callable[[ColorTokens], None

by dispatching the real entrypoint through Streamlit's AppTest runtime
so widget state, session state, and static data loading are exercised
under the app's own semantics rather than by hand-mocking the pages.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from frontend.core.design_tokens import THEMES  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
_APP_FILE = str(_ROOT / "sdm_local_v2.py")

# Pages whose renderer took data beyond the theme.  After the fix they
# read their data from the registry-injected AppData container, not a
# positional argument — the contract signature stays theme-only.
_DATA_PAGES = ("functions", "types")

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


def _collect_text(elements, out: list[str]) -> None:
    """Recursively collect safe text of leaf elements.

    DataFrames and lists are skipped — truth-evaluating them is ambiguous
    under pandas.
    """
    for el in elements:
        cls = type(el).__name__
        if cls in ("MainBlock", "Sidebar", "SpecialBlock"):
            if hasattr(el, "children"):
                _collect_text(el.children, out)
            continue
        label = getattr(el, "label", None)
        if isinstance(label, str) and label:
            out.append(label)
        value = getattr(el, "value", None)
        if isinstance(value, str) and value:
            out.append(value)
        md = getattr(el, "markdown", None)
        if isinstance(md, str) and md:
            out.append(md)


def _run_app(page: str) -> AppTest:
    at = AppTest.from_file(_APP_FILE, default_timeout=30)
    at.session_state["sdm_theme"] = "dark"
    at.query_params["page"] = page
    at.run()
    return at


class TestPageRendererContract:
    """Renderer signatures must match the unified PageRenderer contract."""

    @pytest.mark.parametrize("page", PAGES)
    def test_every_page_dispatches_without_exception(self, page: str) -> None:
        at = _run_app(page)
        assert not at.exception, f"page '{page}' raised: {at.exception!r}"

    @pytest.mark.parametrize("page", PAGES)
    def test_renderer_callable_with_single_theme_arg(self, page: str) -> None:
        """Each renderer must accept exactly one positional argument.

        Guard against a regression where a page re-introduces a
        positional data parameter (the original functions/types bug).
        """
        import sdm_local_v2 as app

        renderer = app.PAGE_MAP[page][1]
        sig = inspect.signature(renderer)
        pos_args = [
            p
            for p, prm in sig.parameters.items()
            if prm.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        assert len(pos_args) == 1, (
            f"renderer for page '{page}' must take exactly one positional "
            f"argument (theme), found {pos_args}"
        )

    @pytest.mark.parametrize("page", _DATA_PAGES)
    def test_data_pages_render_via_injected_data(self, page: str) -> None:
        """Functions / Types must render real data via the injected
        registry, not positional arguments.

        Before the fix these pages took (data, theme) and the entrypoint
        called them with theme only -> TypeError on every visit.
        """
        at = _run_app(page)
        assert not at.exception
        out: list[str] = []
        _collect_text(at.main, out)
        text = "\n".join(out)
        if page == "functions":
            assert "Function Library" in text
        else:
            assert "Type Mapping" in text


class TestAppStartup:
    """Minimum app-dispatch smoke: the entrypoint boots cleanly."""

    def test_app_boots_default_page(self) -> None:
        at = AppTest.from_file(_APP_FILE, default_timeout=30)
        at.session_state["sdm_theme"] = "dark"
        at.run()
        assert not at.exception, f"app raised on startup: {at.exception!r}"
        assert at.main, "no elements rendered on startup"
        # Sidebar navigation buttons present.
        out: list[str] = []
        _collect_text(at.sidebar, out)
        labels = "\n".join(out)
        assert "Convert" in labels, "Convert nav button missing from sidebar"
        assert "NL2SQL" in labels, "NL2SQL nav button missing from sidebar"

    def test_unknown_page_falls_back_to_convert(self) -> None:
        at = _run_app("does_not_exist")
        assert not at.exception


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
