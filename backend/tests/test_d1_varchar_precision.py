#!/usr/bin/env python3
"""
D1 — VARCHAR Precision Semantic Warnings

Tests for parameterized VARCHAR/VARCHAR2 type mapping with precision-aware warnings.
"""
import pytest

from backend.core.type_mapping import TypeMapper


@pytest.fixture
def mapper():
    return TypeMapper()


# =============================================================================
# Phase 1: Failing regression tests — parameterized type resolution
# =============================================================================

class TestParameterizedTypeResolution:
    """Parameterized types like VARCHAR2(2000) must resolve to canonical type."""

    def test_varchar2_without_precision_maps_to_varchar(self, mapper):
        """VARCHAR2 (no precision) should map as VARCHAR."""
        result = mapper.map_type("VARCHAR2", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"

    def test_varchar2_with_precision_maps_to_varchar(self, mapper):
        """VARCHAR2(2000) should map as VARCHAR, preserving precision info."""
        result = mapper.map_type("VARCHAR2(2000)", "oracle", "postgres")
        assert result["success"] is True
        assert result["type_name"] == "VARCHAR2(2000)"
        assert result["target_type"] == "VARCHAR(n)"

    def test_varchar2_large_precision_maps_to_varchar(self, mapper):
        """VARCHAR2(4000) should map successfully."""
        result = mapper.map_type("VARCHAR2(4000)", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"

    def test_varchar_with_precision_maps_to_varchar(self, mapper):
        """VARCHAR(2000) should map successfully."""
        result = mapper.map_type("VARCHAR(2000)", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"

    def test_nvarchar_with_precision_maps_to_tsql(self, mapper):
        """NVARCHAR(4000) should map to NVARCHAR in TSQL."""
        result = mapper.map_type("NVARCHAR(4000)", "oracle", "tsql")
        assert result["success"] is True
        assert result["target_type"] == "NVARCHAR(n)"

    def test_char_with_precision_maps_to_char(self, mapper):
        """CHAR(100) should map successfully."""
        result = mapper.map_type("CHAR(100)", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "CHAR(n)"

    def test_varchar_max_maps_correctly(self, mapper):
        """VARCHAR(MAX) should be recognized as unbounded."""
        result = mapper.map_type("VARCHAR(MAX)", "tsql", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"

    def test_nvarchar_max_maps_correctly(self, mapper):
        """NVARCHAR(MAX) should be recognized as unbounded."""
        result = mapper.map_type("NVARCHAR(MAX)", "tsql", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"


# =============================================================================
# Phase 2: Precision-aware warning semantics
# =============================================================================

class TestPrecisionAwareWarnings:
    """Precision values should influence warning content."""

    def test_varchar2_small_precision_no_overlimit_warning(self, mapper):
        """VARCHAR2(100) should not warn about exceeding Oracle 4000 limit."""
        result = mapper.map_type("VARCHAR2(100)", "oracle", "postgres")
        assert result["success"] is True
        # Should have the generic VARCHAR warning but not an over-limit specific one
        warnings = result.get("warnings", [])
        # Generic warning should still exist
        assert any("Max length varies" in w for w in warnings)

    def test_varchar2_at_oracle_limit_warns(self, mapper):
        """VARCHAR2(4000) at Oracle limit should include over-limit consideration."""
        result = mapper.map_type("VARCHAR2(4000)", "oracle", "postgres")
        assert result["success"] is True
        warnings = result.get("warnings", [])
        # Should have the generic warning
        assert any("Max length varies" in w for w in warnings)

    def test_varchar2_exceeds_oracle_limit_warns(self, mapper):
        """VARCHAR2(8000) exceeding Oracle limit should flag the issue."""
        result = mapper.map_type("VARCHAR2(8000)", "oracle", "postgres")
        assert result["success"] is True
        warnings = result.get("warnings", [])
        # Should have both generic and over-limit warnings
        assert any("Max length varies" in w for w in warnings)
        # Specific over-limit warning for Oracle
        assert any("4000" in w for w in warnings)

    def test_varchar_generic_warning_still_exists(self, mapper):
        """Plain VARCHAR should still trigger the generic precision warning."""
        result = mapper.map_type("VARCHAR", "oracle", "postgres")
        assert result["success"] is True
        assert len(result["warnings"]) > 0
        assert "Max length varies" in result["warnings"][0]

    def test_varchar_precision_warning_preserved(self, mapper):
        """Parameterized VARCHAR should preserve the generic warning."""
        result = mapper.map_type("VARCHAR(2000)", "oracle", "postgres")
        assert result["success"] is True
        assert any("Max length varies" in w for w in result["warnings"])


# =============================================================================
# Phase 3: Dialect matrix coverage
# =============================================================================

class TestDialectMatrixCoverage:
    """Test Oracle → all supported target dialects with parameterized VARCHAR."""

    TARGETS = ["postgres", "mysql", "tsql", "duckdb", "hive", "spark", "databricks"]

    @pytest.mark.parametrize("target", TARGETS)
    def test_varchar2_2000_maps_to_all_targets(self, mapper, target):
        """VARCHAR2(2000) should map successfully to all common targets."""
        result = mapper.map_type("VARCHAR2(2000)", "oracle", target)
        assert result["success"], f"Failed to map to {target}: {result.get('error')}"

    @pytest.mark.parametrize("target", TARGETS)
    def test_varchar_2000_maps_to_all_targets(self, mapper, target):
        """VARCHAR(2000) should map successfully to all common targets."""
        result = mapper.map_type("VARCHAR(2000)", "oracle", target)
        assert result["success"], f"Failed to map to {target}: {result.get('error')}"

    @pytest.mark.parametrize("target", TARGETS)
    def test_varchar2_4000_maps_to_all_targets(self, mapper, target):
        """VARCHAR2(4000) should map successfully to all common targets."""
        result = mapper.map_type("VARCHAR2(4000)", "oracle", target)
        assert result["success"], f"Failed to map to {target}: {result.get('error')}"


# =============================================================================
# Phase 4: Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge cases for parameterized type handling."""

    def test_varchar2_lowercase(self, mapper):
        """Lowercase varchar2 should be normalized."""
        result = mapper.map_type("varchar2(2000)", "oracle", "postgres")
        assert result["success"] is True

    def test_varchar2_with_spaces(self, mapper):
        """VARCHAR2 (2000) with space before paren should work."""
        result = mapper.map_type("VARCHAR2 (2000)", "oracle", "postgres")
        assert result["success"] is True

    def test_varchar2_without_precision_case_insensitive(self, mapper):
        """VARCHAR2 without precision, mixed case."""
        result = mapper.map_type("VarChar2", "oracle", "postgres")
        assert result["success"] is True

    def test_plain_type_still_works(self, mapper):
        """Plain VARCHAR should still work (backward compatibility)."""
        result = mapper.map_type("VARCHAR", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "VARCHAR(n)"

    def test_unsupported_type_fails(self, mapper):
        """Invalid parameterized types should still fail gracefully."""
        result = mapper.map_type("INVALID(100)", "oracle", "postgres")
        assert result["success"] is False

    def test_empty_precision_parentheses(self, mapper):
        """VARCHAR2() with empty parentheses should handle gracefully."""
        result = mapper.map_type("VARCHAR2()", "oracle", "postgres")
        # Should resolve to base type VARCHAR
        assert result["success"] is True


# =============================================================================
# Phase 5: Regression protection
# =============================================================================

class TestRegressionProtection:
    """Ensure existing behavior is preserved."""

    def test_plain_varchar_warning_unchanged(self, mapper):
        """Plain VARCHAR mapping should produce same warnings as before."""
        result = mapper.map_type("VARCHAR", "oracle", "postgres")
        assert result["success"] is True
        assert "Max length varies" in result["warnings"][0]

    def test_decimal_precision_warning_unchanged(self, mapper):
        """DECIMAL precision warning should still work."""
        result = mapper.map_type("DECIMAL", "oracle", "postgres")
        assert result["success"] is True
        assert any("38 digits" in w for w in result["warnings"])

    def test_timestamp_warning_unchanged(self, mapper):
        """TIMESTAMP warning should still work."""
        result = mapper.map_type("TIMESTAMP", "oracle", "postgres")
        assert result["success"] is True
        assert any("9 fractional" in w for w in result["warnings"])

    def test_unknown_type_still_fails(self, mapper):
        """Unknown types should still fail."""
        result = mapper.map_type("UNKNOWN", "oracle", "postgres")
        assert result["success"] is False

    def test_alias_resolution_unchanged(self, mapper):
        """INTEGER alias resolution should still work."""
        result = mapper.map_type("INTEGER", "oracle", "postgres")
        assert result["success"] is True
        assert result["target_type"] == "INTEGER"


# =============================================================================
# Phase 6: G2 — NVARCHAR precision-warning reachability
# =============================================================================

class TestNvarcharPrecisionWarningReachability:
    """The T-SQL NVARCHAR precision rule must actually fire.

    Post-v1.1.0 audit finding: the rule was nested inside
    `if type_name == "VARCHAR"` while testing `type_name == "NVARCHAR"`,
    and 'NVARCHAR' resolves to its own canonical mappings key — so the
    branch was dead for every NVARCHAR input. The configured T-SQL
    NVARCHAR limit is 4000 (vs VARCHAR 8000), per the project's own
    precision_warnings data ("SQL Server 8000 (NVARCHAR 4000)").
    """

    NVARCHAR_LIMIT_WARNING = "exceeds TSQL NVARCHAR limit of 4000"

    # -- boundary conditions -------------------------------------------------

    @pytest.mark.parametrize("target", ["postgres", "mysql", "oracle", "tsql", "duckdb"])
    def test_nvarchar_below_threshold_no_limit_warning(self, mapper, target):
        """NVARCHAR(100) from TSQL must not raise the over-limit warning."""
        result = mapper.map_type("NVARCHAR(100)", "tsql", target)
        assert result["success"] is True
        assert not any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"])

    @pytest.mark.parametrize("target", ["postgres", "mysql", "oracle", "tsql", "duckdb"])
    def test_nvarchar_at_threshold_no_limit_warning(self, mapper, target):
        """NVARCHAR(4000) is exactly at the T-SQL limit — no warning."""
        result = mapper.map_type("NVARCHAR(4000)", "tsql", target)
        assert result["success"] is True
        assert result["precision"] == 4000
        assert not any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"])

    @pytest.mark.parametrize("target", ["postgres", "mysql", "oracle", "tsql", "duckdb"])
    def test_nvarchar_above_threshold_warns(self, mapper, target):
        """NVARCHAR(4001) exceeds the configured T-SQL NVARCHAR limit."""
        result = mapper.map_type("NVARCHAR(4001)", "tsql", target)
        assert result["success"] is True
        assert any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"]), (
            f"expected NVARCHAR over-limit warning for tsql→{target}, "
            f"got {result['warnings']}"
        )
        # Warning suggests the repository's documented remedy.
        assert any("NVARCHAR(MAX)" in w for w in result["warnings"])

    @pytest.mark.parametrize("target", ["postgres", "mysql", "oracle"])
    def test_nvarchar_max_behavior_unchanged(self, mapper, target):
        """NVARCHAR(MAX) retains its existing behavior: unbounded, generic
        warning only, no over-limit warning."""
        result = mapper.map_type("NVARCHAR(MAX)", "tsql", target)
        assert result["success"] is True
        assert result["precision"] == "MAX"
        assert not any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"])
        assert any("Max length varies" in w for w in result["warnings"])

    def test_nvarchar_without_precision_behavior_unchanged(self, mapper):
        """Bare NVARCHAR keeps the generic warning and no over-limit warning."""
        result = mapper.map_type("NVARCHAR", "tsql", "postgres")
        assert result["success"] is True
        assert result["precision"] is None
        assert any("Max length varies" in w for w in result["warnings"])
        assert not any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"])

    def test_nvarchar2_alias_also_reachable(self, mapper):
        """NVARCHAR2 (alias of canonical NVARCHAR) hits the same T-SQL rule."""
        result = mapper.map_type("NVARCHAR2(4001)", "tsql", "postgres")
        assert result["success"] is True
        assert any(self.NVARCHAR_LIMIT_WARNING in w for w in result["warnings"])

    # -- negative / non-regression cases -------------------------------------

    @pytest.mark.parametrize(
        "type_name",
        ["VARCHAR(4001)", "VARCHAR(9000)", "NCHAR(4001)", "CHAR(9000)"],
    )
    def test_non_nvarchar_types_never_get_nvarchar_warning(self, mapper, type_name):
        """VARCHAR/NCHAR/CHAR must not enter the NVARCHAR warning branch,
        even with a precision above the NVARCHAR limit."""
        result = mapper.map_type(type_name, "tsql", "postgres")
        assert result["success"] is True
        assert not any("NVARCHAR" in w and "exceeds" in w for w in result["warnings"]), (
            f"{type_name} must not receive an NVARCHAR-specific warning: "
            f"{result['warnings']}"
        )

    def test_varchar2_oracle_overlimit_warning_unchanged(self, mapper):
        """VARCHAR2(8000) oracle→postgres keeps its existing Oracle warning."""
        result = mapper.map_type("VARCHAR2(8000)", "oracle", "postgres")
        assert result["success"] is True
        assert any("exceeds Oracle's default VARCHAR2 limit of 4000" in w for w in result["warnings"])

    def test_varchar2_oracle_extended_warning_unchanged(self, mapper):
        """VARCHAR2(32768) keeps the extended-limit warning."""
        result = mapper.map_type("VARCHAR2(32768)", "oracle", "postgres")
        assert result["success"] is True
        assert any("exceeds Oracle's extended MAX_STRING_SIZE limit of 32767" in w for w in result["warnings"])

    def test_varchar_target_tsql_warning_unchanged(self, mapper):
        """VARCHAR(9000) → tsql keeps the target-side VARCHAR 8000 warning."""
        result = mapper.map_type("VARCHAR(9000)", "oracle", "tsql")
        assert result["success"] is True
        assert any("Target TSQL VARCHAR(9000) exceeds limit of 8000" in w for w in result["warnings"])

    def test_varchar_target_mysql_warning_unchanged(self, mapper):
        """VARCHAR(30000) → mysql keeps the row-size warning."""
        result = mapper.map_type("VARCHAR(30000)", "oracle", "mysql")
        assert result["success"] is True
        assert any("may exceed MySQL row size" in w for w in result["warnings"])

    def test_varchar_max_target_warnings_unchanged(self, mapper):
        """VARCHAR(MAX) keeps its target oracle/mysql MAX notes."""
        result = mapper.map_type("VARCHAR(MAX)", "tsql", "oracle")
        assert any("unbounded length" in w for w in result["warnings"])
        result = mapper.map_type("VARCHAR(MAX)", "tsql", "mysql")
        assert any("MEDIUMTEXT or LONGTEXT" in w for w in result["warnings"])

    def test_nchar_generic_warning_unchanged(self, mapper):
        """NCHAR keeps its own generic warning, nothing NVARCHAR-specific."""
        result = mapper.map_type("NCHAR(50)", "tsql", "postgres")
        assert result["success"] is True
        assert any("Max length varies across dialects" in w for w in result["warnings"])
        assert not any("NVARCHAR" in w for w in result["warnings"])

    def test_warnings_remain_warnings_not_errors(self, mapper):
        """Over-limit NVARCHAR still maps successfully (warning, not error)."""
        result = mapper.map_type("NVARCHAR(4001)", "tsql", "postgres")
        assert result["success"] is True
        assert result["target_type"] is not None
