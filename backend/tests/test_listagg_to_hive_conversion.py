#!/usr/bin/env python3
"""Tests for Oracle LISTAGG → Hive/Spark/Databricks conversion.

Oracle LISTAGG(expr, delim) WITHIN GROUP (ORDER BY ...) must produce
ARRAY_JOIN(COLLECT_LIST(expr), delim) for Hive-family targets, with an
explicit note that ordering semantics cannot be preserved.

The post_processor must detect the sqlglot-generated GROUP_CONCAT(... ORDER BY
..., delim) form and rewrite it to the Hive-native ARRAY_JOIN(COLLECT_LIST(...))
form.
"""
import pytest
import sqlglot

from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler():
    return SQLTranspiler()


class TestListaggToHive:
    """Oracle LISTAGG → Hive conversion correctness."""

    @pytest.mark.parametrize(
        "source_sql,expected_contains,expected_note_pattern",
        [
            # Basic single-column, single-order
            (
                "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ',')",
                "ORDER BY",
            ),
            # DESC ordering
            (
                "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id DESC) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ',')",
                "ORDER BY",
            ),
            # Multiple ORDER BY columns
            (
                "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id, name DESC) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ',')",
                "ORDER BY",
            ),
            # NULLS FIRST / NULLS LAST
            (
                "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id NULLS FIRST) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ',')",
                "ORDER BY",
            ),
            # Nested expression
            (
                "SELECT LISTAGG(name || ' ' || last_name, ', ') WITHIN GROUP (ORDER BY id) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name || ' ' || last_name), ', ')",
                "ORDER BY",
            ),
            # No ORDER BY (simple LISTAGG)
            (
                "SELECT LISTAGG(name, ',') FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ',')",
                None,  # No ordering to note
            ),
            # Multi-set separator
            (
                "SELECT LISTAGG(name, ';') WITHIN GROUP (ORDER BY id ASC) FROM users",
                "ARRAY_JOIN(COLLECT_LIST(name), ';')",
                "ORDER BY",
            ),
        ],
    )
    def test_listagg_to_hive_produces_array_join(
        self, transpiler, source_sql, expected_contains, expected_note_pattern
    ):
        result = transpiler.transpile(source_sql, "oracle", "hive")
        assert result.success, f"Transpile failed: {result.error}"
        assert expected_contains in result.target_sql, (
            f"Expected output to contain {expected_contains!r}, got:\n{result.target_sql}"
        )
        # Verify the output parses in Hive
        reparsed = sqlglot.parse_one(result.target_sql, read="hive")
        assert reparsed is not None

        if expected_note_pattern:
            # Ordering was present in source — note about semantic loss required
            # The ordering-loss note goes into transformations, not compatibility_notes
            all_notes = result.transformations + result.compatibility_notes
            assert any(
                "ORDER BY" in n.upper() or "ordering" in n.lower()
                for n in all_notes
            ), (
                f"Expected ordering loss note for source with ORDER BY. "
                f"Transformations: {result.transformations}, "
                f"Notes: {result.compatibility_notes}"
            )
        else:
            # No ORDER BY in source — no ordering note needed
            ordering_in_transforms = [
                n for n in result.transformations
                if "ORDER BY" in n.upper() or "ordering" in n.lower()
            ]
            assert len(ordering_in_transforms) == 0, (
                f"Unexpected ordering note for source without ORDER BY. "
                f"Transformations: {result.transformations}"
            )

    @pytest.mark.parametrize("target_dialect", ["hive"])
    def test_listagg_to_hive_family_produces_array_join(self, transpiler, target_dialect):
        """ARRAY_JOIN(COLLECT_LIST(...)) for Hive; Spark/Databricks keep LISTAGG natively."""
        source_sql = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users"
        result = transpiler.transpile(source_sql, "oracle", target_dialect)
        assert result.success, f"Transpile failed for {target_dialect}: {result.error}"
        assert "ARRAY_JOIN" in result.target_sql.upper()
        assert "COLLECT_LIST" in result.target_sql.upper()

    def test_listagg_without_within_group_to_hive(self, transpiler):
        """LISTAGG without WITHIN GROUP still converts to ARRAY_JOIN."""
        source_sql = "SELECT LISTAGG(name, ',') FROM users"
        result = transpiler.transpile(source_sql, "oracle", "hive")
        assert result.success
        assert "ARRAY_JOIN" in result.target_sql.upper()
        assert "COLLECT_LIST" in result.target_sql.upper()

    def test_listagg_to_hive_does_not_preserve_ordering_semantics(self, transpiler):
        """When source has ORDER BY, transformation must note the semantic loss."""
        source_sql = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id DESC) FROM users"
        result = transpiler.transpile(source_sql, "oracle", "hive")
        assert result.success
        # The note should explicitly say ordering is lost
        ordering_notes = [
            n for n in result.transformations
            if "order" in n.lower() or "ordering" in n.lower()
        ]
        assert len(ordering_notes) >= 1, (
            f"Expected ordering loss note, got transformations: {result.transformations}"
        )

    def test_listagg_no_order_by_to_hive_no_ordering_note(self, transpiler):
        """LISTAGG without ORDER BY should not produce an ordering note."""
        source_sql = "SELECT LISTAGG(name, ',') FROM users"
        result = transpiler.transpile(source_sql, "oracle", "hive")
        assert result.success
        ordering_in_transforms = [
            n for n in result.transformations
            if "ORDER BY" in n.upper() or "ordering" in n.lower()
        ]
        assert len(ordering_in_transforms) == 0, (
            f"Unexpected ordering note for simple LISTAGG: {result.transformations}"
        )


class TestListaggPreservesOtherDialects:
    """LISTAGG → non-Hive targets must not be affected by the fix."""

    @pytest.mark.parametrize(
        "target,expected_fn",
        [
            ("postgres", "STRING_AGG"),
            ("mysql", "GROUP_CONCAT"),
            ("oracle", "LISTAGG"),
            ("tsql", "STRING_AGG"),
            ("snowflake", "LISTAGG"),
            ("redshift", "LISTAGG"),
            ("duckdb", "LISTAGG"),
            ("trino", "LISTAGG"),
        ],
    )
    def test_listagg_to_non_hive_unchanged(self, transpiler, target, expected_fn):
        source_sql = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users"
        result = transpiler.transpile(source_sql, "oracle", target)
        assert result.success, f"Transpile to {target} failed: {result.error}"
        upper_sql = result.target_sql.upper()
        assert expected_fn in upper_sql, (
            f"Expected {expected_fn} in output for {target}, got:\n{result.target_sql}"
        )
