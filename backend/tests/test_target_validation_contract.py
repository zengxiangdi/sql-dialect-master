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
        self, transpiler: SQLTranspiler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deterministic unit: target parser rejects but generic accepts ->
        generic_only, with a warning, and no error.  The generic fallback
        must never be presented as a clean target validation.

        This is monkeypatch-based so it does NOT depend on any particular
        natural SQL string happening to trip a specific sqlglot dialect
        parser.  The failure mode is forced deterministically.
        """
        import sqlglot

        real_parse_one = sqlglot.parse_one

        def fake_parse_one(sql, read=None, **kwargs):
            # First call (target-dialect validation, read=target) -> force fail
            # Second call (generic validation, read=None) -> succeed
            if read is not None:
                raise sqlglot.errors.ParseError(f"forced target parser reject: {sql}")
            return real_parse_one(sql)

        monkeypatch.setattr(sqlglot, "parse_one", fake_parse_one)

        error, warning, state = transpiler._validate_output_detailed(
            "SELECT 1 FROM t", "mysql"
        )
        assert state == "generic_only", (
            f"Expected 'generic_only' but got {state!r} — the forced "
            "target-fail/generic-pass path must always produce generic_only"
        )
        assert error is None, "generic_only must not set error"
        assert warning is not None, "generic_only must set a warning"
        assert "target dialect parser rejected" in warning.lower() or "target" in warning.lower(), (
            f"warning must describe target-dialect rejection, got: {warning!r}"
        )

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
        """End-to-end guard: a real transpile whose output the target
        dialect really accepted must still read as target_valid (not
        generic_only).  This test verifies the non-generic path remains
        intact for the specific SQL chosen here."""
        result = transpiler.transpile(
            "SELECT id FROM users LIMIT 10", "postgres", "mysql"
        )
        assert result.success is True
        assert result.target_validation_state == "target_valid"

    def test_transpile_propagates_generic_only_to_result(
        self, transpiler: SQLTranspiler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production-path: transpile() must propagate the generic_only
        state to TranspileResult.target_validation_state.

        This monkeypatches _validate_output_detailed so that the
        forced-failure scenario (target parser rejects, generic parser
        accepts) is guaranteed regardless of sqlglot version.  It
        exercises the full transpile() → TranspileResult → to_dict()
        → ConvertResponse path without depending on a specific natural
        SQL string.
        """
        import sqlglot

        real_parse_one = sqlglot.parse_one

        def fake_parse_one(sql, read=None, **kwargs):
            if read is not None:
                raise sqlglot.errors.ParseError("forced target reject")
            return real_parse_one(sql)

        monkeypatch.setattr(sqlglot, "parse_one", fake_parse_one)

        # Full transpile() path: source=postgres → target=mysql
        # The real sqlglot.transpile() call at the top of transpile()
        # also uses sqlglot.parse_one (for clickhouse/oracle/etc. fast
        # paths).  For postgres→mysql, the generic sqlglot.transpile
        # branch is taken (line ~251), which does NOT use parse_one
        # for the transpile step itself — only _validate_output_detailed
        # does.  So the fake only affects validation, which is exactly
        # the path under test.
        result = transpiler.transpile("SELECT 1 FROM t", "postgres", "mysql")

        # The fake forces target validation to fail, so transpile()
        # enters the generic fallback:
        #   generic_parse succeeds → generic_only (not invalid)
        #   → TranspileResult(target_validation_state="generic_only")
        assert result.success is True, (
            "generic_only must still be a successful conversion (not blocked)"
        )
        assert result.target_validation_state == "generic_only", (
            f"Expected generic_only but got {result.target_validation_state!r} — "
            "transpile() did not propagate the generic fallback state"
        )
        assert any(
            "target dialect parser rejected" in w.lower()
            for w in result.warnings
        ), (
            "generic_only warning must be present in TranspileResult.warnings"
        )

        # Wire format: to_dict() must carry the state.
        d = result.to_dict()
        assert d["target_validation_state"] == "generic_only"

        # API wire: ConvertResponse must preserve it.
        from backend.api.main import ConvertResponse

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
        assert resp.target_validation_state == "generic_only"
        assert resp.model_dump()["target_validation_state"] == "generic_only"

    def test_transpile_propagates_invalid_when_both_parsers_fail(
        self, transpiler: SQLTranspiler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production-path: when both target and generic parsers reject
        the output, transpile() must return success=False with state
        'invalid' — never presenting a broken conversion as successful."""
        import sqlglot

        real_parse_one = sqlglot.parse_one

        def fake_parse_one(sql, read=None, **kwargs):
            # Both target and generic parser calls fail.
            # The transpile() step (sqlglot.transpile) is not patched,
            # so transpilation itself succeeds; only the validation
            # step (which calls parse_one) fails.
            raise sqlglot.errors.ParseError(f"forced reject ({read})")

        monkeypatch.setattr(sqlglot, "parse_one", fake_parse_one)

        result = transpiler.transpile("SELECT 1 FROM t", "postgres", "mysql")

        # _validate_output_detailed: target fails, generic fails →
        #   returns (error=..., warning=None, state="invalid")
        # transpile() then: validation_error is not None →
        #   returns TranspileResult(success=False, target_validation_state="invalid")
        assert result.success is False, (
            "invalid state must make transpile() report success=False"
        )
        assert result.target_validation_state == "invalid", (
            f"Expected 'invalid' but got {result.target_validation_state!r}"
        )
        assert result.error is not None, "invalid state must carry an error"

        d = result.to_dict()
        assert d["target_validation_state"] == "invalid"


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
