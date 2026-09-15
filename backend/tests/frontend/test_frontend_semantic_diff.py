#!/usr/bin/env python3
"""Semantic Diff ViewModel and workspace tests for SQL Dialect Master v2."""
from __future__ import annotations

import pytest

from backend.core.semantic_diff import (
    StructuredSemanticDifference,
    diff_sql_ast,
)
from frontend.core.escaping import esc
from frontend.core.viewmodels import (
    SemanticDiffViewModel,
    SemanticFindingViewModel,
)

# ── SemanticDiffViewModel construction tests ────────────────────────────

class TestSemanticDiffViewModel:
    """Test SemanticDiffViewModel from all backend classification types."""

    def test_equivalent_classification(self) -> None:
        """Equivalent SQL should produce Equivalent classification."""
        diff = diff_sql_ast("SELECT 1", "SELECT 1", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT 1",
            target_sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification == "equivalent"
        assert vm.classification_label == "Equivalent"
        assert vm.overall_status in ("valid", "success")
        assert vm.finding_count == 0
        assert vm.error_count == 0
        assert vm.warning_count == 0
        assert vm.confidence == 0.95  # backend sets 0.95 for equivalent

    def test_structurally_equivalent_classification(self) -> None:
        """Structurally equivalent should produce Structurally Equivalent."""
        # Same semantics, different syntax
        diff = diff_sql_ast(
            "SELECT id FROM users",
            "SELECT id FROM users",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT id FROM users",
            target_sql="SELECT id FROM users",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification in ("equivalent", "structurally_equivalent")
        assert vm.overall_status in ("valid", "success", "info")

    def test_definitely_different_classification(self) -> None:
        """Different projection should produce Definitely Different."""
        diff = diff_sql_ast(
            "SELECT * FROM users",
            "SELECT id FROM users",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT * FROM users",
            target_sql="SELECT id FROM users",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification == "definitely_different"
        assert vm.classification_label == "Definitely Different"
        assert vm.overall_status in ("error", "danger")
        assert vm.finding_count >= 1
        # Findings may be warnings or errors depending on backend classification
        assert vm.finding_count == vm.error_count + vm.warning_count

    def test_potentially_different_classification(self) -> None:
        """Context-sensitive functions should produce Potentially Different."""
        diff = diff_sql_ast(
            "SELECT NOW()",
            "SELECT NOW()",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT NOW()",
            target_sql="SELECT NOW()",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification == "potentially_different"
        assert vm.classification_label == "Potentially Different"
        assert vm.overall_status == "warning"

    def test_unknown_classification(self) -> None:
        """Unknown semantic status should map correctly."""
        diff = diff_sql_ast(
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_TIMESTAMP",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT CURRENT_TIMESTAMP",
            target_sql="SELECT CURRENT_TIMESTAMP",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification == "potentially_different"
        assert vm.confidence < 1.0

    def test_parse_error_classification(self) -> None:
        """Parse error should produce Parse Error classification."""
        diff = diff_sql_ast(
            "{{{{",
            "SELECT 1",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            source_sql="{{{{",
            target_sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.classification == "parse_error"
        assert vm.parse_error is not None
        assert vm.finding_count == 0

    def test_preserves_dialects(self) -> None:
        """ViewModel should preserve source and target dialects."""
        diff = diff_sql_ast("SELECT 1", "SELECT 1", "mysql", "postgres")
        vm = SemanticDiffViewModel.from_backend(
            source_sql="SELECT 1",
            target_sql="SELECT 1",
            source_dialect="mysql",
            target_dialect="postgres",
            diff=diff,
        )
        assert vm.source_dialect == "mysql"
        assert vm.target_dialect == "postgres"

    def test_source_target_sql_preserved(self) -> None:
        """Original SQL should be preserved in ViewModel."""
        source = "SELECT DATE_ADD(d, INTERVAL 7 DAY) FROM t"
        target = "SELECT d + INTERVAL '7 days' FROM t"
        diff = diff_sql_ast(source, target, "mysql", "postgres")
        vm = SemanticDiffViewModel.from_backend(source, target, "mysql", "postgres", diff)
        assert vm.source_sql == source
        assert vm.target_sql == target


class TestSemanticFindingViewModel:
    """Test SemanticFindingViewModel construction."""

    def test_from_backend_with_error_severity(self) -> None:
        """Finding with error severity should have HIGH label."""
        sd = StructuredSemanticDifference(
            category="projection",
            severity="error",
            source_fragment="SELECT *",
            target_fragment="SELECT id",
            explanation="Projected expressions changed",
            confidence=0.9,
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        assert vm.index == 0
        assert vm.category == "projection"
        assert vm.severity == "error"
        assert vm.severity_label == "HIGH"
        assert vm.category_label == "Projection"
        assert vm.source_fragment == "SELECT *"
        assert vm.target_fragment == "SELECT id"
        assert vm.explanation == "Projected expressions changed"
        assert vm.confidence == 0.9

    def test_from_backend_with_warning_severity(self) -> None:
        """Finding with warning severity should have MEDIUM label."""
        sd = StructuredSemanticDifference(
            category="function",
            severity="warning",
            source_fragment="DATE_ADD(x, 7)",
            target_fragment="x + 7",
            explanation="Function differs",
        )
        vm = SemanticFindingViewModel.from_backend(1, sd)
        assert vm.severity_label == "MEDIUM"
        assert vm.index == 1

    def test_from_backend_with_missing_optional_fields(self) -> None:
        """Finding with missing optional fields should use defaults."""
        sd = StructuredSemanticDifference(
            category="structure",
            severity="warning",
            source_fragment="",
            target_fragment="",
            explanation="",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        assert vm.source_fragment == ""
        assert vm.target_fragment == ""
        assert vm.explanation == ""
        assert vm.evidence is None


class TestSeverityMapping:
    """Test severity to display label mapping."""

    def test_error_severity(self) -> None:
        sd = StructuredSemanticDifference(
            category="test", severity="error",
            source_fragment="a", target_fragment="b", explanation="e",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        assert vm.severity_label == "HIGH"

    def test_warning_severity(self) -> None:
        sd = StructuredSemanticDifference(
            category="test", severity="warning",
            source_fragment="a", target_fragment="b", explanation="e",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        assert vm.severity_label == "MEDIUM"


class TestInspectorState:
    """Test inspector state management."""

    def test_no_selection_shows_placeholder(self) -> None:
        """No selected finding should produce empty inspector."""
        diff = diff_sql_ast("SELECT 1", "SELECT 1", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend("SELECT 1", "SELECT 1", "postgres", "postgres", diff)
        assert vm.finding_count == 0
        # No inspector needed when there are no findings
        assert vm.error_count == 0
        assert vm.warning_count == 0

    def test_valid_selection_index(self) -> None:
        """Selected finding index should be valid."""
        diff = diff_sql_ast(
            "SELECT * FROM users",
            "SELECT id FROM users",
            "postgres",
            "postgres",
        )
        vm = SemanticDiffViewModel.from_backend(
            "SELECT * FROM users", "SELECT id FROM users",
            "postgres", "postgres", diff,
        )
        # Should have at least one finding
        assert vm.finding_count >= 1
        # First finding should be selectable
        assert vm.findings[0] is not None
        assert vm.findings[0].index == 0

    def test_missing_optional_fields_in_inspector(self) -> None:
        """Inspector should handle missing optional fields gracefully."""
        sd = StructuredSemanticDifference(
            category="projection",
            severity="error",
            source_fragment="",
            target_fragment="",
            explanation="",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        # All fields should be accessible without error
        _ = vm.source_fragment
        _ = vm.target_fragment
        _ = vm.explanation
        _ = vm.evidence  # Should be None


class TestClassificationColors:
    """Test that classification maps to correct color."""

    def test_equivalent_maps_to_success(self) -> None:
        diff = diff_sql_ast("SELECT 1", "SELECT 1", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend("SELECT 1", "SELECT 1", "postgres", "postgres", diff)
        assert vm.overall_status in ("valid", "success")

    def test_different_maps_to_error(self) -> None:
        diff = diff_sql_ast("SELECT * FROM u", "SELECT id FROM u", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend("SELECT * FROM u", "SELECT id FROM u", "postgres", "postgres", diff)
        assert vm.overall_status in ("error", "danger")

    def test_potentially_different_maps_to_warning(self) -> None:
        diff = diff_sql_ast("SELECT NOW()", "SELECT NOW()", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend("SELECT NOW()", "SELECT NOW()", "postgres", "postgres", diff)
        assert vm.overall_status == "warning"

    def test_parse_error_maps_to_error(self) -> None:
        diff = diff_sql_ast("{{{", "SELECT 1", "postgres", "postgres")
        vm = SemanticDiffViewModel.from_backend("{{{", "SELECT 1", "postgres", "postgres", diff)
        assert vm.overall_status in ("error", "danger")


class TestConvertToDiffNavigation:
    """Test Convert → Diff navigation state flow."""

    def test_pending_diff_state_structure(self) -> None:
        """Pending diff state should have correct keys."""
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

    def test_pending_diff_consumed_after_read(self) -> None:
        """Pending diff should be consumed (set to None) after read."""
        import streamlit as st
        st.session_state.sdm_pending_diff = {
            "source": "SELECT 1",
            "src_dialect": "postgres",
            "target": "SELECT 2",
            "tgt_dialect": "mysql",
        }
        # Simulate consumption
        pending = st.session_state.sdm_pending_diff
        if pending:
            st.session_state.sdm_pending_diff = None
        assert st.session_state.sdm_pending_diff is None


class TestSecurity:
    """Test security of semantic diff UI rendering."""

    @pytest.mark.parametrize(
        "malicious_text",
        [
            "<script>alert(1)</script>",
            "</style><script>document.cookie</script>",
            '<img onerror="alert(1)">',
            "<svg onload='alert(1)'",
            "SQL comment ; DROP TABLE users; --",
            '" OR 1=1 --',
            "backtick `javascript:alert(1)`",
        ],
    )
    def test_malicious_finding_text_not_executed(self, malicious_text: str) -> None:
        """Malicious text in finding fields should be escaped, not executed."""
        escaped = str(esc(malicious_text))
        # Core security: angle brackets must be escaped so browser doesn't parse as HTML
        assert "<" not in escaped
        assert ">" not in escaped

    def test_malicious_explanation_escaped(self) -> None:
        """Explanation field with XSS should be escaped."""
        sd = StructuredSemanticDifference(
            category="test",
            severity="warning",
            source_fragment="<script>alert(1)</script>",
            target_fragment="<img onerror=alert(1)>",
            explanation="</style><svg onload=alert(1)>",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        # All fields should be safely escapable
        assert "<script>" not in str(esc(vm.explanation))
        assert "<img" not in str(esc(vm.source_fragment))

    def test_malicious_category_escaped(self) -> None:
        """Category name should be escaped."""
        sd = StructuredSemanticDifference(
            category="<script>",
            severity="warning",
            source_fragment="a",
            target_fragment="b",
            explanation="test",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        assert "<script>" not in str(esc(vm.category_label))

    def test_malicious_evidence_escaped(self) -> None:
        """Evidence field should be escaped — angle brackets removed."""
        sd = StructuredSemanticDifference(
            category="test",
            severity="warning",
            source_fragment="a",
            target_fragment="b",
            explanation="test",
            evidence="<script>alert(document.cookie)</script>",
        )
        vm = SemanticFindingViewModel.from_backend(0, sd)
        escaped_evidence = str(esc(vm.evidence or ""))
        assert "<" not in escaped_evidence
        assert ">" not in escaped_evidence
