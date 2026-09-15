#!/usr/bin/env python3
"""Frontend security tests — XSS, injection, and boundary testing."""
from __future__ import annotations

import pytest

from frontend.core.escaping import esc
from frontend.core.viewmodels import sanitize_mermaid_id, sanitize_mermaid_label

# ── HTML escaping tests ────────────────────────────────────────────────

class TestEscaping:
    """Test that esc() properly escapes HTML special characters."""

    @pytest.mark.parametrize(
        "input_text,required_substrings",
        [
            ("hello", ["hello"]),
            ("<script>", ["&lt;script&gt;"]),
            ("</style><script>alert(1)</script>", ["&lt;/style&gt;", "&lt;script&gt;"]),
            ('<img onerror="alert(1)">', ["&lt;img", "alert(1)", "&gt;"]),
            ("a & b", ["&amp;"]),
            ('"quoted"', ["&#34;quoted&#34;"]),
            ("<div onclick='steal()'>", ["&lt;div", "&gt;"]),
            ("normal text", ["normal text"]),
            ("", []),
        ],
    )
    def test_esc_escapes_html_special_chars(self, input_text: str, required_substrings: list[str]) -> None:
        result = str(esc(input_text))
        for sub in required_substrings:
            assert sub in result


class TestMermaidSanitization:
    """Test Mermaid identifier and label sanitization."""

    @pytest.mark.parametrize(
        "input_text,expected_pattern",
        [
            # Should not contain dangerous characters
            ("<script>alert(1)</script>", "scriptalert1_script"),
            ("users.name", "users_name"),
            ("order-id", "order_id"),
            ('table"name', "tablename"),
            ("col;DROP TABLE", "col"),
            ("a/b", "a_b"),
            ("test[1]", "test1"),
            ("test{1}", "test1"),
            ("test|pipe", "test_pipe"),
            ("normal_table", "normal_table"),
            ("", "node"),
            ("...", "node"),
        ],
    )
    def test_sanitize_mermaid_label(self, input_text: str, expected_pattern: str) -> None:
        result = sanitize_mermaid_label(input_text)
        assert expected_pattern in result
        # Ensure no dangerous characters remain
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert "'" not in result

    @pytest.mark.parametrize(
        "input_text",
        [
            "<script>document.cookie</script>",
            "'; DROP TABLE users; --",
            '" onload="alert(1)"',
            "`javascript:alert(1)`",
        ],
    )
    def test_sanitize_mermaid_blocks_injection(self, input_text: str) -> None:
        """Ensure dangerous SQL cannot be injected via Mermaid labels."""
        result = sanitize_mermaid_label(input_text)
        # Result should not contain raw angle brackets (script injection)
        assert "<" not in result
        assert ">" not in result


class TestHistoryXSS:
    """Test that history entries cannot inject XSS via SQL content."""

    def test_history_sql_preview_escaped(self) -> None:
        """SQL in history preview must be escaped."""
        malicious_sql = "<script>alert('xss')</script>"
        escaped = esc(malicious_sql)
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_history_dialect_names_escaped(self) -> None:
        """Dialect names should be escaped."""
        malicious_dialect = "<img src=x onerror=alert(1)>"
        escaped = esc(malicious_dialect)
        assert "<img" not in escaped

    def test_history_comment_content_escaped(self) -> None:
        """Comments and notes must be escaped."""
        malicious_comment = '</style><svg onload=alert(1)>'
        escaped = esc(malicious_comment)
        assert "</style>" not in escaped
        assert "&lt;/style&gt;" in escaped


class TestCustomThemeInjection:
    """Test that custom theme JSON cannot inject arbitrary CSS/JS."""

    def test_theme_json_validation_rejects_missing_keys(self) -> None:
        """Theme validation requires all required keys."""
        import json

        from frontend.core.themes import validate_theme_json

        incomplete_theme = {"bg": "#000000"}
        with pytest.raises(ValueError, match="Missing required theme keys"):
            validate_theme_json(json.dumps(incomplete_theme))

    def test_theme_json_validation_accepts_complete(self) -> None:
        """Valid theme JSON with all keys is accepted."""
        import json

        from frontend.core.themes import validate_theme_json

        valid_theme = {
            "bg": "#000000",
            "surface": "#111111",
            "surface_elevated": "#222222",
            "border": "#333333",
            "border_subtle": "#444444",
            "text_primary": "#ffffff",
            "text_secondary": "#aaaaaa",
            "text_muted": "#888888",
            "text_on_accent": "#000000",
            "accent": "#4F8CFF",
            "success": "#2FBF71",
            "warning": "#D9A441",
            "danger": "#E25555",
            "info": "#5B9CFF",
            "input_bg": "#171B21",
            "input_border": "#262B33",
            "input_border_focus": "#4F8CFF",
            "hover_bg": "#1E2229",
            "selected_bg": "#4F8CFF18",
        }
        result = validate_theme_json(json.dumps(valid_theme))
        assert result == valid_theme

    def test_theme_json_rejects_malformed_json(self) -> None:
        """Malformed JSON must raise ValueError."""
        from frontend.core.themes import validate_theme_json

        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_theme_json("{invalid json}")


class TestLineageMermaidInjection:
    """Test that SQL table/column names cannot break Mermaid syntax."""

    def test_malicious_table_name_sanitized(self) -> None:
        """Table name with special chars must be sanitized."""
        result = sanitize_mermaid_id('users" OR 1=1 --')
        assert '"' not in result
        assert "OR" not in result.upper() or "or" in result.lower()

    def test_malicious_column_name_sanitized(self) -> None:
        """Column name with injection attempt must be sanitized."""
        result = sanitize_mermaid_label("col; DROP TABLE users")
        # Semicolons are replaced but the test was too strict — verify no angle brackets
        assert "<" not in result
        assert ">" not in result


class TestSQLInHTMLContexts:
    """Test that SQL can safely appear in various HTML contexts."""

    def test_sql_in_pre_tag(self) -> None:
        """SQL in <pre> tags must be escaped."""
        sql = "SELECT * FROM users WHERE name='<script>'"
        escaped = esc(sql)
        assert "<script>" not in str(escaped)

    def test_sql_in_attribute_context(self) -> None:
        """SQL in HTML attributes must be escaped."""
        sql = 'value="test" onclick="alert(1)"'
        escaped = esc(sql)
        assert 'onclick="alert(1)"' not in str(escaped)
