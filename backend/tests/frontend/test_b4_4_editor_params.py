"""B4-4 — the SQL editor must not pass unsupported widget params.

``st.text_area`` has no ``horizontal`` parameter; passing it raises at
call time.  The component is exercised for real (AppTest renders it),
not just string-searched.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


class TestB4_4_EditorCallLevel:
    def test_editor_renders_without_exception(self):
        def script():
            import streamlit as st
            from frontend.core.design_tokens import DARK
            from frontend.ui.editor import render_sql_editor

            value = render_sql_editor(
                "b4_editor",
                "SQL",
                value="SELECT 1",
                height=120,
                theme=DARK,
            )
            st.write(value)

        at = AppTest.from_function(script, default_timeout=60)
        at.run()
        assert not at.exception, at.exception
        # The text area exists and carries the initial value.
        assert any(el.key == "b4_editor" for el in at.text_area)
        for el in at.text_area:
            if el.key == "b4_editor":
                assert el.value == "SELECT 1"
