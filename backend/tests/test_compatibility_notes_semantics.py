"""B2-3 — compatibility notes must reflect the ACTUAL conversion.

``_get_compatibility_notes`` previously conflated two responsibilities:

* **Source-construct advisories** — notes triggered by constructs in the
  user's original SQL (e.g. a LIMIT the target must express as
  FETCH FIRST).  These must be detected from the ORIGINAL SQL; a
  successfully converted final SQL no longer contains the source
  construct, so a final-only check would wrongly drop them.
* **Conversion-result claims** — notes asserting a transformation
  happened (e.g. "CONNECT BY ... converted to WITH RECURSIVE",
  "LATERAL VIEW ... converted to UNNEST/JSON_TABLE",
  "LISTAGG → ARRAY_JOIN(COLLECT_LIST()) transformation").  These must
  be verified against the FINAL SQL: the claimed target construct must
  actually appear there.  The old code checked the original SQL for the
  target construct (which never appears there) — dropping real claims
  for the wrong reason, while the bottom-block appends claimed
  conversions based on the original SQL alone, emitting false claims
  when sqlglot left the source construct in place.

The tests below use real ``transpile()`` outputs whenever a real
conversion exists (LIMIT→FETCH FIRST, CONNECT BY→WITH RECURSIVE via
oracle→duckdb, LATERAL VIEW→UNNEST via hive→duckdb, LISTAGG→ARRAY_JOIN
via oracle→hive) and never fake a conversion to make an assertion pass.
"""
from __future__ import annotations

import pytest

from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler():
    return SQLTranspiler()


CONNECT_BY_SQL = (
    "SELECT * FROM users START WITH id = 1 CONNECT BY PRIOR id = parent_id"
)
LATERAL_VIEW_SQL = "SELECT id, tag FROM t LATERAL VIEW explode(tags) t AS tag"
LISTAGG_SQL = "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users"


# ── T1 — LIMIT advisory must survive a successful conversion ─────────────────

class TestT1LimitAdvisorySurvivesConversion:
    @pytest.mark.parametrize("source", ["postgres", "mysql"])
    def test_oracle_fetch_first_conversion_keeps_limit_advisory(
        self, transpiler, source
    ):
        result = transpiler.transpile("SELECT * FROM t LIMIT 5", source, "oracle")
        assert result.success is True, result.error
        # The conversion really happened: source syntax is gone.
        assert "FETCH FIRST" in result.target_sql.upper(), result.target_sql
        assert "LIMIT" not in result.target_sql.upper(), result.target_sql
        # The advisory describing the LIMIT conversion must survive.
        assert any(
            "Oracle uses FETCH FIRST" in note
            for note in result.compatibility_notes
        ), (
            "LIMIT advisory must survive the FETCH FIRST conversion: "
            f"{result.compatibility_notes}"
        )


# ── T2 — CONNECT BY claims must be backed by the final SQL ───────────────────

class TestT2ConnectByClaimBackedByFinalSQL:
    def test_claim_present_when_final_has_with_recursive(
        self, transpiler
    ):
        """oracle→duckdb really produces WITH RECURSIVE; the claim is true."""
        result = transpiler.transpile(CONNECT_BY_SQL, "oracle", "duckdb")
        assert result.success is True, result.error
        assert "WITH RECURSIVE" in result.target_sql.upper(), result.target_sql
        assert any(
            "WITH RECURSIVE" in note for note in result.compatibility_notes
        ), (
            "true CONNECT BY → WITH RECURSIVE conversion must carry its "
            f"claim: {result.compatibility_notes}"
        )

    @pytest.mark.parametrize("target", ["hive", "postgres"])
    def test_no_claim_when_final_keeps_connect_by(self, transpiler, target):
        """sqlglot keeps CONNECT BY for these targets; claiming conversion
        to WITH RECURSIVE is false and must be suppressed."""
        result = transpiler.transpile(CONNECT_BY_SQL, "oracle", target)
        assert result.success is True, result.error
        assert "WITH RECURSIVE" not in result.target_sql.upper(), result.target_sql
        assert "CONNECT BY" in result.target_sql.upper(), result.target_sql
        assert not any(
            "WITH RECURSIVE" in note for note in result.compatibility_notes
        ), (
            f"no WITH RECURSIVE claim allowed when the final SQL still has "
            f"CONNECT BY: {result.compatibility_notes}"
        )

    def test_static_table_claim_requires_final_evidence(self, transpiler):
        """Unit-level: the static (oracle→hive) CONNECT BY note is a
        conversion claim and must follow the final SQL's evidence."""
        notes_with = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=CONNECT_BY_SQL,
            final_sql="WITH RECURSIVE cte AS (SELECT 1) SELECT * FROM cte",
        )
        assert any(
            "CONNECT BY" in n and "WITH RECURSIVE" in n for n in notes_with
        ), notes_with

        notes_without = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=CONNECT_BY_SQL,
            final_sql=CONNECT_BY_SQL,
        )
        assert not any(
            "WITH RECURSIVE" in n for n in notes_without
        ), notes_without


# ── T3 — LATERAL VIEW claims must match the actual output ────────────────────

class TestT3LateralViewClaimMatchesOutput:
    def test_claim_present_when_final_has_unnest(self, transpiler):
        """hive→duckdb really produces CROSS JOIN UNNEST; the claim is true."""
        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "duckdb")
        assert result.success is True, result.error
        assert "UNNEST" in result.target_sql.upper(), result.target_sql
        assert any(
            "LATERAL VIEW" in note and "UNNEST" in note
            for note in result.compatibility_notes
        ), (
            "true LATERAL VIEW → UNNEST conversion must carry its claim: "
            f"{result.compatibility_notes}"
        )

    def test_no_conversion_claim_when_final_keeps_lateral_view(
        self, transpiler
    ):
        """hive→mysql keeps LATERAL VIEW; claiming 'converted to
        UNNEST/JSON_TABLE' is false and must be suppressed."""
        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "mysql")
        assert result.success is True, result.error
        assert "LATERAL VIEW" in result.target_sql.upper(), result.target_sql
        assert "UNNEST" not in result.target_sql.upper(), result.target_sql
        assert "JSON_TABLE" not in result.target_sql.upper(), result.target_sql
        assert not any(
            "converted to UNNEST/JSON_TABLE" in note
            for note in result.compatibility_notes
        ), (
            "no conversion claim allowed when the final SQL still has "
            f"LATERAL VIEW: {result.compatibility_notes}"
        )

    def test_manual_adjustment_advisory_still_present(self, transpiler):
        """The hive→mysql advisory ('may need manual adjustment') is not a
        conversion claim — it stays for a source that really uses
        LATERAL VIEW, without claiming the conversion happened."""
        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "mysql")
        assert result.success is True, result.error
        assert any(
            "may need manual adjustment" in note
            for note in result.compatibility_notes
        ), (
            "advisory must remain for an unconverted LATERAL VIEW source: "
            f"{result.compatibility_notes}"
        )

    def test_static_table_lateral_view_claim_requires_target_evidence(
        self, transpiler
    ):
        """Unit-level: the static (hive→postgres) note claims conversion
        to UNNEST; it must follow the final SQL's evidence."""
        notes_with = transpiler._get_compatibility_notes(
            "hive", "postgres",
            source_sql=LATERAL_VIEW_SQL,
            final_sql="SELECT id, tag FROM t CROSS JOIN UNNEST(tags) AS t(tag)",
        )
        assert any("UNNEST" in n for n in notes_with), notes_with

        notes_without = transpiler._get_compatibility_notes(
            "hive", "postgres",
            source_sql=LATERAL_VIEW_SQL,
            final_sql=LATERAL_VIEW_SQL,
        )
        assert not any(
            "UNNEST" in n and "transformation" in n for n in notes_without
        ), notes_without


# ── T4 — LISTAGG / ARRAY_JOIN claims must follow the final output ────────────

class TestT4ListaggArrayJoinClaims:
    def test_listagg_to_hive_claim_present_when_converted(self, transpiler):
        """oracle→hive really produces ARRAY_JOIN(COLLECT_LIST(...)); the
        static conversion claim must be retained."""
        result = transpiler.transpile(LISTAGG_SQL, "oracle", "hive")
        assert result.success is True, result.error
        assert "ARRAY_JOIN" in result.target_sql.upper(), result.target_sql
        assert any(
            "ARRAY_JOIN" in note for note in result.compatibility_notes
        ), (
            "converted LISTAGG must carry its ARRAY_JOIN claim: "
            f"{result.compatibility_notes}"
        )

    def test_no_listagg_claim_without_source_listagg(self, transpiler):
        """A dialect-pair table entry alone must not emit a conversion
        claim when neither the source nor the final SQL has the construct."""
        result = transpiler.transpile("SELECT 1", "oracle", "hive")
        assert result.success is True, result.error
        assert not any(
            "ARRAY_JOIN" in note or "LISTAGG" in note
            for note in result.compatibility_notes
        ), result.compatibility_notes

    def test_static_listagg_claim_requires_final_evidence(self, transpiler):
        """Unit-level: the (oracle→hive) LISTAGG note requires ARRAY_JOIN
        evidence in the final SQL."""
        notes_with = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=LISTAGG_SQL,
            final_sql="SELECT ARRAY_JOIN(COLLECT_LIST(name), ',') FROM users",
        )
        assert any("ARRAY_JOIN" in n for n in notes_with), notes_with

        notes_without = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=LISTAGG_SQL,
            final_sql=LISTAGG_SQL,  # conversion never happened
        )
        assert not any("ARRAY_JOIN" in n for n in notes_without), notes_without


# ── T5 — generic source advisories keep their source-based detection ─────────

class TestT5SourceAdvisoryNotesSurvive:
    def test_auto_increment_advisory_is_source_based(self, transpiler):
        """AUTO_INCREMENT is detected on the source SQL; the advisory must
        not depend on the final SQL containing AUTO_INCREMENT."""
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="CREATE TABLE x (id INT AUTO_INCREMENT PRIMARY KEY)",
            final_sql="CREATE TABLE x (id SERIAL PRIMARY KEY)",
        )
        assert any(
            "AUTO_INCREMENT" in n and "varies" in n for n in notes
        ), notes

    def test_merge_advisory_is_source_based(self, transpiler):
        result = transpiler.transpile(
            "MERGE INTO t USING s ON (t.id = s.id) "
            "WHEN MATCHED THEN UPDATE SET t.v = s.v",
            "postgres", "mysql",
        )
        assert result.success is True, result.error
        assert any(
            "MERGE syntax varies" in note
            for note in result.compatibility_notes
        ), result.compatibility_notes

    def test_pivot_advisory_is_source_based(self, transpiler):
        result = transpiler.transpile(
            "SELECT * FROM t PIVOT (SUM(v) FOR k IN ('a','b'))",
            "oracle", "postgres",
        )
        assert result.success is True, result.error
        assert any(
            "PIVOT/UNPIVOT syntax varies" in note
            for note in result.compatibility_notes
        ), result.compatibility_notes
