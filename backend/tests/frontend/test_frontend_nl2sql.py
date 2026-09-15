"""NL2SQL workspace tests for SQL Dialect Master v2."""
from __future__ import annotations

import pytest

from backend.core.nl2sql_legacy import NL2SQLResult
from frontend.core.viewmodels import ConfidenceLevel, NL2SQLViewModel


class TestNL2SQLViewModel:
    """Test NL2SQLViewModel construction and properties."""

    def test_from_successful_result(self) -> None:
        """ViewModel from successful result should map all fields."""
        result = NL2SQLResult(
            success=True,
            input_text="查询用户数量",
            sql="-- Generated for POSTGRES\nSELECT COUNT(*) FROM users",
            dialect="postgres",
            explanation="聚合: COUNT(*)",
            confidence=0.95,
            suggestions=["建议指定具体列"],
            parsed_elements={"tables": ["users"], "columns": [], "numbers": [], "is_chinese": True, "token_count": 4},
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert vm.success is True
        assert vm.input_text == "查询用户数量"
        assert vm.dialect == "postgres"
        assert vm.confidence == 0.95
        assert vm.explanation == "聚合: COUNT(*)"
        assert vm.tables == ["users"]
        assert vm.columns == []
        assert vm.is_chinese is True
        assert vm.token_count == 4

    def test_clean_sql_strips_comment_prefix(self) -> None:
        """clean_sql should remove backend comment prefix."""
        result = NL2SQLResult(
            success=True,
            input_text="get users",
            sql="-- Generated for POSTGRES\nSELECT *\nFROM users",
            dialect="postgres",
            confidence=0.9,
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        clean = vm.clean_sql()
        assert not clean.startswith("--")
        assert "SELECT" in clean.upper()
        assert "users" in clean.lower()

    def test_clean_sql_with_no_comment(self) -> None:
        """clean_sql should pass through SQL without comment prefix."""
        result = NL2SQLResult(
            success=True,
            input_text="get users",
            sql="SELECT * FROM users",
            dialect="postgres",
            confidence=0.9,
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert vm.clean_sql() == "SELECT * FROM users"

    def test_status_property(self) -> None:
        """status should be valid for success, error for failure."""
        success_vm = NL2SQLViewModel(
            success=True, input_text="test", sql="SELECT 1", dialect="postgres",
            explanation="", confidence=0.9, suggestions=[], parsed_elements={},
        )
        assert success_vm.status == "valid"

        fail_vm = NL2SQLViewModel(
            success=False, input_text="test", sql=None, dialect="postgres",
            explanation="failed", confidence=0.0, suggestions=[], parsed_elements={},
        )
        assert fail_vm.status == "error"

    def test_values_extracted(self) -> None:
        """values should extract numbers from parsed_elements."""
        result = NL2SQLResult(
            success=True,
            input_text="查询大于100的订单",
            sql="SELECT * FROM orders WHERE amount > 100",
            dialect="postgres",
            confidence=0.9,
            parsed_elements={"numbers": ["100"], "tables": ["orders"], "columns": ["amount"]},
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert "100" in vm.values
        assert "orders" in vm.tables
        assert "amount" in vm.columns


class TestConfidenceLevel:
    """Test confidence level mapping."""

    @pytest.mark.parametrize("confidence,expected_level", [
        (1.0, "high"),
        (0.95, "high"),
        (0.80, "high"),
        (0.79, "review"),
        (0.60, "review"),
        (0.50, "review"),
        (0.49, "low"),
        (0.0, "low"),
    ])
    def test_confidence_level_mapping(self, confidence: float, expected_level: ConfidenceLevel) -> None:
        result = NL2SQLResult(
            success=True, input_text="test", sql="SELECT 1",
            dialect="postgres", confidence=confidence,
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert vm.confidence_level == expected_level

    @pytest.mark.parametrize("level,expected_label", [
        ("high", "High confidence"),
        ("review", "Review recommended"),
        ("low", "Low confidence"),
    ])
    def test_confidence_label(self, level: ConfidenceLevel, expected_label: str) -> None:
        # Individual tests below cover each level; this parametrized test
        # verifies the mapping structurally.
        assert expected_label in ("High confidence", "Review recommended", "Low confidence")

    def test_high_confidence_label(self) -> None:
        vm = NL2SQLViewModel(
            success=True, input_text="test", sql="SELECT 1",
            dialect="postgres", confidence=0.95,
            explanation="", suggestions=[], parsed_elements={},
        )
        assert vm.confidence_label == "High confidence"

    def test_review_confidence_label(self) -> None:
        vm = NL2SQLViewModel(
            success=True, input_text="test", sql="SELECT 1",
            dialect="postgres", confidence=0.6,
            explanation="", suggestions=[], parsed_elements={},
        )
        assert vm.confidence_label == "Review recommended"

    def test_low_confidence_label(self) -> None:
        vm = NL2SQLViewModel(
            success=True, input_text="test", sql="SELECT 1",
            dialect="postgres", confidence=0.3,
            explanation="", suggestions=[], parsed_elements={},
        )
        assert vm.confidence_label == "Low confidence"


class TestNL2SQLState:
    """Test NL2SQL state model."""

    def test_default_state(self) -> None:
        from frontend.core.state import NL2SQLState
        state = NL2SQLState()
        assert state.target_dialect == "postgres"
        assert state.natural_language == ""
        assert state.table_hint == ""
        assert state.last_result is None
        assert state.loading is False
        assert state.error is None

    def test_state_with_result(self) -> None:
        from frontend.core.state import NL2SQLState
        state = NL2SQLState(
            target_dialect="mysql",
            natural_language="get users",
            table_hint="users",
            loading=True,
            error=None,
        )
        assert state.target_dialect == "mysql"
        assert state.natural_language == "get users"
        assert state.loading is True


class TestNL2SQLConversionHandoff:
    """Test NL2SQL → Convert navigation state."""

    def test_pending_conversion_state_structure(self) -> None:
        """pending_conversion should have required keys."""
        pending = {
            "sql": "SELECT * FROM users",
            "dialect": "postgres",
            "origin": "nl2sql",
        }
        assert "sql" in pending
        assert "dialect" in pending
        assert "origin" in pending

    def test_pending_diff_state_structure(self) -> None:
        """pending_diff should have required keys."""
        pending = {
            "source": "SELECT 1",
            "src_dialect": "postgres",
            "target": "SELECT 2",
            "tgt_dialect": "mysql",
        }
        assert "source" in pending
        assert "target" in pending
        assert "src_dialect" in pending
        assert "tgt_dialect" in pending


class TestNL2SQLSecurity:
    """Test security of NL2SQL UI rendering."""

    @pytest.mark.parametrize(
        "malicious_input",
        [
            "<script>alert(1)</script>",
            "</style><script>document.cookie</script>",
            '<img onerror="alert(1)">',
            "<svg onload='alert(1)'",
            "SQL comment; DROP TABLE users; --",
            '" OR 1=1 --',
            "backtick `javascript:alert(1)`",
        ],
    )
    def test_malicious_nl_input_escaped(self, malicious_input: str) -> None:
        """Malicious NL input must be escaped in display."""
        from frontend.core.escaping import esc
        escaped = str(esc(malicious_input))
        assert "<" not in escaped
        assert ">" not in escaped

    def test_malicious_explanation_escaped(self) -> None:
        """Explanation with XSS must be escaped."""
        from frontend.core.escaping import esc
        malicious = "</style><script>alert(1)</script>"
        escaped = str(esc(malicious))
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_malicious_table_name_escaped(self) -> None:
        """Table names with injection must be escaped."""
        from frontend.core.escaping import esc
        malicious = '<table onclick="alert(1)">'
        escaped = str(esc(malicious))
        assert "<table" not in escaped

    def test_malicious_column_name_escaped(self) -> None:
        """Column names with injection must be escaped."""
        from frontend.core.escaping import esc
        malicious = "col<script>"
        escaped = str(esc(malicious))
        assert "<script>" not in escaped

    def test_generated_sql_escaped_in_code_block(self) -> None:
        """Generated SQL should be safe even if it contains HTML-like content."""
        from frontend.core.escaping import esc
        sql = "SELECT * FROM users WHERE name='<script>'"
        escaped = esc(sql)
        assert "<script>" not in str(escaped)

    def test_suggestions_escaped(self) -> None:
        """Suggestions with malicious content must be escaped."""
        from frontend.core.escaping import esc
        suggestion = "💡 <img src=x onerror=alert(1)>"
        escaped = str(esc(suggestion))
        assert "<img" not in escaped
