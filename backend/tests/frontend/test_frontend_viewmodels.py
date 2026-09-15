#!/usr/bin/env python3
"""Frontend viewmodel tests."""
from __future__ import annotations

from backend.core.nl2sql_legacy import NL2SQLResult
from backend.core.semantic_diff import (
    SemanticDiff,
    diff_sql_ast,
)
from frontend.core.viewmodels import (
    BatchConversionViewModel,
    ConversionViewModel,
    LineageTable,
    LineageViewModel,
    NL2SQLViewModel,
    sanitize_mermaid_id,
    sanitize_mermaid_label,
)


class TestConversionViewModel:
    """Test ConversionViewModel from various sources."""

    def test_from_transpile_result_success(self) -> None:
        """ViewModel from successful TranspileResult."""
        from backend.core.transpiler import TranspileResult
        result = TranspileResult(
            success=True,
            source_sql="SELECT 1",
            target_sql="SELECT 1",
            source_dialect="postgres",
            target_dialect="mysql",
            transformations=["test"],
            warnings=[],
            compatibility_notes=[],
        )
        vm = ConversionViewModel.from_transpile_result(result)
        assert vm.status == "valid"
        assert vm.syntax_status == "ok"
        assert vm.ast_status == "ok"
        assert vm.semantic_status == "pending"
        assert vm.error_message is None
        assert vm.source_dialect == "postgres"
        assert vm.target_dialect == "mysql"

    def test_from_transpile_result_error(self) -> None:
        """ViewModel from failed TranspileResult."""
        from backend.core.transpiler import TranspileResult
        result = TranspileResult(
            success=False,
            source_sql="INVALID",
            source_dialect="postgres",
            target_dialect="mysql",
            error="Parse error",
        )
        vm = ConversionViewModel.from_transpile_result(result)
        assert vm.status == "error"
        assert vm.syntax_status == "error"
        assert vm.error_message == "Parse error"

    def test_from_semantic_diff_equivalent(self) -> None:
        """ViewModel enriched with equivalent semantic diff."""
        from backend.core.transpiler import TranspileResult
        base = ConversionViewModel.from_transpile_result(
            TranspileResult(
                success=True,
                source_sql="SELECT 1",
                target_sql="SELECT 1",
                source_dialect="postgres",
                target_dialect="mysql",
            )
        )
        diff = SemanticDiff(
            equivalent=True,
            source_normalized="SELECT 1",
            target_normalized="SELECT 1",
            status="equivalent",
            semantic_classification="equivalent",
            confidence=1.0,
        )
        enriched = ConversionViewModel.from_semantic_diff(base, diff)
        assert enriched.semantic_status == "equivalent"
        assert enriched.semantic_label == "Equivalent"

    def test_from_semantic_diff_different(self) -> None:
        """ViewModel enriched with different semantic diff."""
        from backend.core.transpiler import TranspileResult
        base = ConversionViewModel.from_transpile_result(
            TranspileResult(
                success=True,
                source_sql="SELECT 1",
                target_sql="SELECT 2",
                source_dialect="postgres",
                target_dialect="mysql",
            )
        )
        diff = diff_sql_ast("SELECT 1", "SELECT 2", "postgres", "mysql")
        enriched = ConversionViewModel.from_semantic_diff(base, diff)
        assert enriched.semantic_status in ("different", "unknown")


class TestNL2SQLViewModel:
    """Test NL2SQLViewModel construction."""

    def test_from_successful_result(self) -> None:
        """ViewModel from successful NL2SQLResult."""
        result = NL2SQLResult(
            success=True,
            input_text="Get all users",
            sql="SELECT * FROM users",
            dialect="postgres",
            explanation="Simple select",
            confidence=0.95,
            suggestions=[],
            parsed_elements={"tables": ["users"]},
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert vm.success is True
        assert vm.sql == "SELECT * FROM users"
        assert vm.confidence == 0.95
        assert vm.status == "valid"

    def test_from_failed_result(self) -> None:
        """ViewModel from failed NL2SQLResult."""
        result = NL2SQLResult(
            success=False,
            input_text="garbage",
            sql=None,
            explanation="Could not parse",
            confidence=0.1,
        )
        vm = NL2SQLViewModel.from_nl2sql_result(result)
        assert vm.success is False
        assert vm.sql is None
        assert vm.status == "error"


class TestBatchConversionViewModel:
    """Test BatchConversionViewModel."""

    def test_from_results_with_mixed_outcomes(self) -> None:
        """ViewModel from mixed success/failure results."""
        from backend.core.transpiler import TranspileResult
        statements = ["SELECT 1", "INVALID"]
        results = [
            TranspileResult(success=True, source_sql="SELECT 1", target_sql="SELECT 1",
                          source_dialect="postgres", target_dialect="mysql"),
            TranspileResult(success=False, source_sql="INVALID", source_dialect="postgres",
                          target_dialect="mysql", error="Parse error"),
        ]
        bvm = BatchConversionViewModel.from_results(statements, results)
        assert bvm.total == 2
        assert bvm.succeeded == 1
        assert bvm.failed == 1
        assert bvm.items[0].success is True
        assert bvm.items[1].success is False


class TestLineageViewModel:
    """Test LineageViewModel."""

    def test_empty_lineage(self) -> None:
        """Empty lineage should have no tables or columns."""
        vm = LineageViewModel.empty("postgres", "SELECT 1")
        assert vm.tables == []
        assert vm.output_columns == []
        assert vm.column_references == {}

    def test_lineage_with_tables(self) -> None:
        """Lineage with tables should store them."""
        vm = LineageViewModel(
            dialect="postgres",
            sql="SELECT * FROM users",
            tables=[LineageTable(name="users")],
        )
        assert len(vm.tables) == 1
        assert vm.tables[0].name == "users"


class TestMermaidSanitization:
    """Test Mermaid-safe string functions."""

    def test_sanitize_label_removes_dangerous_chars(self) -> None:
        """sanitize_mermaid_label should remove dangerous characters."""
        assert "<script>" not in sanitize_mermaid_label("<script>alert(1)</script>")
        assert '"' not in sanitize_mermaid_label('table"name')

    def test_sanitize_id_alphanumeric(self) -> None:
        """sanitize_mermaid_id should produce alphanumeric IDs."""
        result = sanitize_mermaid_id("user-id_123")
        assert result.replace("_", "").isalnum()

    def test_sanitize_id_starts_with_letter(self) -> None:
        """sanitize_mermaid_id should start with a letter."""
        result = sanitize_mermaid_id("123table")
        assert result[0].isalpha()
