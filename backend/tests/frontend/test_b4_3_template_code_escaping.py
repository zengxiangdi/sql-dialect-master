"""B4-3 — template SQL code blocks must render raw SQL, not HTML-escaped text.

``st.code`` displays its argument literally; passing HTML-escaped SQL
there shows ``&gt;`` entities to the user and corrupts copy-paste.
HTML escaping stays only on ``st.markdown(..., unsafe_allow_html=True)``
regions.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


class TestB4_3_TemplateCodeBlock:
    def test_template_code_shows_raw_sql(self):
        """Render the real templates page, expand every template, and
        verify code blocks show raw SQL (no HTML entities)."""

        def script():
            from frontend.core.design_tokens import DARK
            from frontend.pages.templates import render_templates_page

            render_templates_page(DARK)

        at = AppTest.from_function(script, default_timeout=60)
        at.run()
        assert not at.exception, at.exception

        # AppTest exposes code elements inside expanders without
        # needing to expand them.
        code_texts = [str(el.value) for el in at.code]
        joined = "\n".join(code_texts)
        # Real templates carry comparison operators (">", "<=") and
        # quoted strings — the displayed SQL must keep them verbatim.
        assert ">" in joined
        assert "&gt;" not in joined
        assert "&lt;" not in joined
        assert "&quot;" not in joined
        assert "&amp;" not in joined
        # The HAVING template must appear in its exact raw form.
        assert (
            "HAVING COUNT(*) > 5" in joined
        ), f"raw SQL expected in code blocks, got: {joined[:300]}"
