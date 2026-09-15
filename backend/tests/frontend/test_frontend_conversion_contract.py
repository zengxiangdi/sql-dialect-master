#!/usr/bin/env python3
"""Frontend conversion contract tests."""
from __future__ import annotations

import pytest

from backend.core.transpiler import SQLTranspiler, TranspileResult
from frontend.app_context_v2 import convert_sql, batch_convert_sql, format_sql_local
from frontend.core.viewmodels import ConversionViewModel, BatchConversionViewModel


@pytest.fixture
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


class TestConvertContract:
    """Test that convert_sql returns proper TranspileResult."""

    def test_basic_conversion(self, transpiler: SQLTranspiler) -> None:
        """Basic SQL conversion should succeed."""
        sql = "SELECT * FROM users"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success is True
        assert result.target_sql is not None
        assert "SELECT" in result.target_sql.upper()

    def test_conversion_with_where(self, transpiler: SQLTranspiler) -> None:
        """Conversion with WHERE clause should preserve conditions."""
        sql = "SELECT id, name FROM users WHERE status = 'active'"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success is True
        assert "WHERE" in result.target_sql.upper()

    def test_conversion_failure_on_invalid_sql(self, transpiler: SQLTranspiler) -> None:
        """Invalid SQL should fail gracefully."""
        sql = "THIS IS NOT SQL {{{{"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success is False

    def test_conversion_empty_sql(self, transpiler: SQLTranspiler) -> None:
        """Empty SQL should fail."""
        result = transpiler.transpile("", "postgres", "mysql")
        assert result.success is False
        assert "Empty" in result.error

    def test_conversion_unsupported_dialect(self, transpiler: SQLTranspiler) -> None:
        """Unsupported dialect should fail."""
        result = transpiler.transpile("SELECT 1", "postgres", "unknown_dialect")
        assert result.success is False
        assert "Unsupported" in result.error


class TestBatchConvertContract:
    """Test batch conversion API contract."""

    def test_batch_basic(self, transpiler: SQLTranspiler) -> None:
        """Basic batch conversion should work."""
        statements = ["SELECT 1", "SELECT 2"]
        results = transpiler.batch_transpile(statements, "postgres", "mysql")
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_batch_mixed_success_failure(self, transpiler: SQLTranspiler) -> None:
        """Batch with mixed success/failure should handle correctly."""
        statements = ["SELECT 1", "{{{{"]
        results = transpiler.batch_transpile(statements, "postgres", "mysql")
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False

    def test_batch_empty_statements(self, transpiler: SQLTranspiler) -> None:
        """Empty batch should return empty results."""
        results = transpiler.batch_transpile([], "postgres", "mysql")
        assert results == []

    def test_batch_single_statement(self, transpiler: SQLTranspiler) -> None:
        """Single statement batch should work."""
        results = transpiler.batch_transpile(["SELECT 1"], "postgres", "mysql")
        assert len(results) == 1
        assert results[0].success is True


class TestFormatSqlContract:
    """Test SQL formatting contract."""

    def test_format_basic(self) -> None:
        """Format should return valid SQL."""
        sql = "select 1"
        result = format_sql_local(sql, "postgres")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_preserves_semantics(self) -> None:
        """Formatting should preserve SQL semantics."""
        sql = "SELECT * FROM users WHERE id = 1"
        result = format_sql_local(sql, "postgres")
        assert "SELECT" in result.upper()
        assert "FROM" in result.upper()
        assert "users" in result.lower()


class TestConversionViewModel:
    """Test ConversionViewModel construction."""

    def test_from_successful_result(self, transpiler: SQLTranspiler) -> None:
        """ViewModel from successful result should have valid status."""
        result = transpiler.transpile("SELECT 1", "postgres", "mysql")
        vm = ConversionViewModel.from_transpile_result(result)
        assert vm.status == "valid"
        assert vm.syntax_status == "ok"
        assert vm.ast_status == "ok"
        assert vm.semantic_status == "pending"
        assert vm.target_sql is not None

    def test_from_failed_result(self, transpiler: SQLTranspiler) -> None:
        """ViewModel from failed result should have error status."""
        result = transpiler.transpile("{{{{", "postgres", "mysql")
        vm = ConversionViewModel.from_transpile_result(result)
        assert vm.status == "error"
        assert vm.syntax_status == "error"
        assert vm.error_message is not None

    def test_vm_preserves_dialects(self, transpiler: SQLTranspiler) -> None:
        """ViewModel should preserve source and target dialects."""
        result = transpiler.transpile("SELECT 1", "postgres", "snowflake")
        vm = ConversionViewModel.from_transpile_result(result)
        assert vm.source_dialect == "postgres"
        assert vm.target_dialect == "snowflake"


class TestBatchConversionViewModel:
    """Test BatchConversionViewModel construction."""

    def test_from_results(self, transpiler: SQLTranspiler) -> None:
        """ViewModel from batch results should compute correct counts."""
        statements = ["SELECT 1", "SELECT 2", "{{{{"]
        results = transpiler.batch_transpile(statements, "postgres", "mysql")
        bvm = BatchConversionViewModel.from_results(statements, results)
        assert bvm.total == 3
        assert bvm.succeeded == 2
        assert bvm.failed == 1
        assert abs(bvm.success_rate - 2/3) < 0.01

    def test_empty_results(self) -> None:
        """Empty results should have zero rates."""
        bvm = BatchConversionViewModel(total=0, succeeded=0, failed=0)
        assert bvm.success_rate == 0.0
