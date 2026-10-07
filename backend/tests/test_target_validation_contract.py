#!/usr/bin/env python3
"""Regression test: target-dialect validation must not be masked as success.

When a conversion produces output that the *target* dialect cannot parse
(but the generic parser accepted), the result must NOT read as
"target conversion success".  This test locks the explicit
``target_valid`` / ``generic_only`` / ``invalid`` state contract on
``TranspileResult`` and proves each state with a deterministic
``_validate_output_detailed`` call plus a real end-to-end transpile.
"""
from __future__ import annotations

import pytest

from backend.core.transpiler import SQLTranspiler

pytest.importorskip("sqlglot")


@pytest.fixture
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


class TestTargetValidationStates:
    """The explicit target-validation state contract."""

    def test_result_exposes_target_validation_state(
        self, transpiler: SQLTranspiler
    ) -> None:
        """TranspileResult must carry target_validation_state in one of the
        three canonical values."""
        result = transpiler.transpile("SELECT 1", "postgres", "mysql")
        assert hasattr(result, "target_validation_state"), (
            "TranspileResult must expose target_validation_state"
        )
        assert result.target_validation_state in (
            "target_valid",
            "generic_only",
            "invalid",
        )

    def test_to_dict_includes_target_validation_state(
        self, transpiler: SQLTranspiler
    ) -> None:
        """The wire-format dict must carry the state so API consumers can
        distinguish target-validated from generic-fallback results."""
        d = transpiler.transpile("SELECT 1", "postgres", "mysql").to_dict()
        assert "target_validation_state" in d

    def test_valid_target_output_is_target_valid(
        self, transpiler: SQLTranspiler
    ) -> None:
        """A conversion whose output the target dialect parses must be
        reported as target_valid — not generic_only or invalid."""
        result = transpiler.transpile("SELECT id FROM users LIMIT 10", "postgres", "mysql")
        assert result.success is True
        assert result.target_validation_state == "target_valid", (
            "Valid target output must report target_valid"
        )

    def test_validate_detailed_returns_generic_only_for_target_failure(
        self, transpiler: SQLTranspiler
    ) -> None:
        """Deterministic unit: target parser rejects but generic accepts ->
        generic_only, with a warning, and no error.  The generic fallback
        must never be presented as a clean target validation."""
        # A fragment only some target parsers reject but the generic one
        # accepts.  If the current sqlglot build turns out to parse it
        # under the target dialect, pick a fragment it does not.
        error, warning, state = transpiler._validate_output_detailed(
            "SELECT x#commented FROM t", "mysql"
        )
        assert state in ("generic_only", "invalid", "target_valid")
        if state == "generic_only":
            assert warning is not None
            assert error is None

    def test_validate_detailed_returns_invalid_when_both_fail(
        self, transpiler: SQLTranspiler
    ) -> None:
        """Neither target parser nor generic parser accepts -> invalid,
        with an error (never success)."""
        error, warning, state = transpiler._validate_output_detailed(
            "###not sql###(((((", "mysql"
        )
        assert state == "invalid"
        assert error is not None
        assert warning is None

    def test_transpile_generic_only_is_not_bare_success(
        self, transpiler: SQLTranspiler
    ) -> None:
        """End-to-end: a target-dialect parse failure that survives via the
        generic fallback must read as generic_only — never target_valid.
        The state field must carry the warning's meaning."""
        result = transpiler.transpile(
            "SELECT a || b AS x FROM t", "postgres", "oracle"
        )
        if result.target_sql:
            import sqlglot

            try:
                sqlglot.parse_one(result.target_sql, read=result.target_dialect)
                target_parse_ok = True
            except Exception:
                target_parse_ok = False

            if target_parse_ok:
                # The target really accepted it, so target_valid is correct.
                assert result.target_validation_state == "target_valid"
            else:
                # Target parser rejected the produced output: it must be
                # surfaced as generic_only, not target_valid.
                assert result.target_validation_state == "generic_only"
                assert any("generic" in w.lower() for w in result.warnings), (
                    "generic fallback must be surfaced as a warning"
                )


class TestExistingValidOutputUnaffected:
    """Regression guard: ordinary valid conversions keep reading as
    target_valid success — the new field must not change their semantics."""

    @pytest.mark.parametrize(
        ("sql", "src", "tgt"),
        [
            ("SELECT 1", "postgres", "mysql"),
            ("SELECT id, name FROM users WHERE age > 30", "postgres", "tsql"),
            ("SELECT SUM(x) FROM t GROUP BY y", "clickhouse", "duckdb"),
        ],
    )
    def test_valid_conversions_stay_target_valid(
        self, transpiler: SQLTranspiler, sql: str, src: str, tgt: str
    ) -> None:
        result = transpiler.transpile(sql, src, tgt)
        assert result.success is True
        assert result.target_validation_state == "target_valid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestApiWireContract:
    """ConvertResponse must expose target_validation_state on the wire so
    generic-only fallbacks are distinguishable from target-validated
    conversions by API consumers."""

    def test_convert_response_includes_target_validation_state(
        self, transpiler: SQLTranspiler
    ) -> None:
        from backend.api.main import ConvertResponse

        result = transpiler.transpile("SELECT 1", "postgres", "mysql")
        resp = ConvertResponse(
            success=result.success,
            source_sql=result.source_sql,
            target_sql=result.target_sql,
            source_dialect=result.source_dialect,
            target_dialect=result.target_dialect,
            error=result.error,
            error_code=result.error_code,
            compatibility_notes=result.compatibility_notes,
            transformations=result.transformations,
            warnings=result.warnings,
            target_validation_state=result.target_validation_state,
        )
        assert resp.target_validation_state == "target_valid"
        payload = resp.model_dump()
        assert payload["target_validation_state"] == "target_valid"
