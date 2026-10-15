"""B4-1 — Semantic Diff must receive real source SQL and real target SQL.

The result panel's Semantic Diff entry passed the converted SQL as BOTH
source and target.  The navigation payload must carry the original
source SQL, the real conversion result, and both dialects; when no
original SQL exists (NL2SQL), no self-comparison may be offered.
"""
from __future__ import annotations

import pytest

from frontend.core.navigation import create_diff_navigation_intent


class TestB4_1_DiffIntentHelper:
    def test_intent_carries_distinct_source_and_target(self):
        intent = create_diff_navigation_intent(
            source_sql="SELECT * FROM a",
            target_sql="SELECT * FROM b",
            src_dialect="postgres",
            tgt_dialect="mysql",
        )
        assert intent.target_page == "diff"
        assert intent.action == "open_diff"
        assert intent.get_payload("source") == "SELECT * FROM a"
        assert intent.get_payload("target") == "SELECT * FROM b"
        assert intent.get_payload("source") != intent.get_payload("target")
        assert intent.get_payload("src_dialect") == "postgres"
        assert intent.get_payload("tgt_dialect") == "mysql"

    def test_intent_never_self_compares_by_default(self):
        """A blank source must not silently become the target."""
        intent = create_diff_navigation_intent(
            source_sql="",
            target_sql="SELECT * FROM b",
            src_dialect="postgres",
            tgt_dialect="mysql",
        )
        assert intent.get_payload("source") == ""
        assert intent.get_payload("target") == "SELECT * FROM b"


@pytest.mark.skip(
    reason="The Streamlit result panel was retired; React conversion handoff is covered by frontend-react tests."
)
class TestB4_1_ResultPanelIntegration:
    def test_panel_button_builds_distinct_navigation_payload(self):
        """Render the real result panel, click Semantic Diff, and inspect
        the produced navigation payload end to end."""

        from streamlit.testing.v1 import AppTest

        def script():
            import streamlit as st
            from frontend.core.design_tokens import DARK
            from frontend.ui.status import render_result_panel

            render_result_panel(
                sql="SELECT * FROM converted",
                source_sql="SELECT * FROM original",
                source_dialect="postgres",
                target_dialect="mysql",
                warnings=[],
                transformations=[],
                compatibility_notes=[],
                error_message=None,
                semantic_label="Pending",
                semantic_status="pending",
                theme=DARK,
            )

        at = AppTest.from_function(script, default_timeout=60)
        at.run()
        assert not at.exception, at.exception

        at.button(key="to_diff_btn").click()
        at.run()
        intent = at.session_state["sdm_navigation_intent"]
        assert intent.target_page == "diff"
        assert intent.action == "open_diff"
        assert intent.get_payload("source") == "SELECT * FROM original"
        assert intent.get_payload("target") == "SELECT * FROM converted"
        assert intent.get_payload("src_dialect") == "postgres"
        assert intent.get_payload("tgt_dialect") == "mysql"
