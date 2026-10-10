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


# ── B2-3a T1 — classification completeness ───────────────────────────────────

class TestB23A_T1_StaticClaimClassificationComplete:
    """Every static note that EXPLICITLY claims a conversion happened
    (wording: "transformation" / "converted to") must have a Class B
    evidence rule.  Unmatched explicit claims silently passing through
    is exactly the defect this test guards against."""

    def test_every_explicit_conversion_claim_has_evidence_rule(self):
        from backend.core.config import COMPATIBILITY_NOTES
        from backend.core.transpiler import _CONVERSION_NOTE_EVIDENCE

        markers = [marker.upper() for marker, _, _ in _CONVERSION_NOTE_EVIDENCE]
        unclassified = []
        for (source, target), notes in COMPATIBILITY_NOTES.items():
            for note in notes:
                upper = note.upper()
                explicit_claim = (
                    "TRANSFORMATION" in upper or "CONVERTED TO" in upper
                )
                if explicit_claim and not any(m in upper for m in markers):
                    unclassified.append(f"({source}->{target}) {note!r}")
        assert not unclassified, (
            f"unclassified explicit conversion claims: {unclassified}"
        )


# ── B2-3a T2 — GROUP_CONCAT → STRING_AGG ─────────────────────────────────────

class TestB23A_T2_GroupConcatToStringAgg:
    def test_claim_present_when_conversion_happens(self, transpiler):
        result = transpiler.transpile(
            "SELECT GROUP_CONCAT(name SEPARATOR ',') FROM users",
            "mysql", "postgres",
        )
        assert result.success is True, result.error
        assert "STRING_AGG" in result.target_sql.upper(), result.target_sql
        assert any(
            "GROUP_CONCAT" in n and "STRING_AGG" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_claim_suppressed_when_final_keeps_group_concat(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="SELECT GROUP_CONCAT(name) FROM users",
            final_sql="SELECT GROUP_CONCAT(name) FROM users",
        )
        assert not any(
            "GROUP_CONCAT" in n and "STRING_AGG" in n for n in notes
        ), notes

    def test_no_claim_without_source_group_concat(self, transpiler):
        result = transpiler.transpile("SELECT 1", "mysql", "postgres")
        assert result.success is True, result.error
        assert not any(
            "GROUP_CONCAT" in n for n in result.compatibility_notes
        ), result.compatibility_notes


# ── B2-3a T3 — IFNULL → COALESCE ──────────────────────────────────────────────

class TestB23A_T3_IfnullToCoalesce:
    def test_claim_present_when_conversion_happens(self, transpiler):
        result = transpiler.transpile(
            "SELECT IFNULL(a, 0) FROM t", "mysql", "postgres"
        )
        assert result.success is True, result.error
        assert "COALESCE" in result.target_sql.upper(), result.target_sql
        assert any(
            "IFNULL" in n and "COALESCE" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_claim_suppressed_when_final_keeps_ifnull(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="SELECT IFNULL(a, 0) FROM t",
            final_sql="SELECT IFNULL(a, 0) FROM t",
        )
        assert not any(
            "IFNULL" in n and "COALESCE" in n for n in notes
        ), notes

    def test_no_claim_when_source_lacks_ifnull_even_with_coalesce_target(
        self, transpiler
    ):
        """COALESCE in the final SQL alone must not trigger the IFNULL
        claim — the source construct is required evidence too."""
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="SELECT COALESCE(a, 0) FROM t",
            final_sql="SELECT COALESCE(a, 0) FROM t",
        )
        assert not any("IFNULL" in n for n in notes), notes


# ── B2-3a T4 — remaining transformation claims ───────────────────────────────

class TestB23A_T4_RemainingTransformationClaims:
    def test_string_agg_group_concat_claim_present(self, transpiler):
        result = transpiler.transpile(
            "SELECT STRING_AGG(name, ',') FROM users", "postgres", "mysql"
        )
        assert result.success is True, result.error
        assert "GROUP_CONCAT" in result.target_sql.upper(), result.target_sql
        assert any(
            "STRING_AGG" in n and "GROUP_CONCAT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_string_agg_claim_suppressed_without_target_evidence(
        self, transpiler
    ):
        notes = transpiler._get_compatibility_notes(
            "postgres", "mysql",
            source_sql="SELECT STRING_AGG(name, ',') FROM users",
            final_sql="SELECT STRING_AGG(name, ',') FROM users",
        )
        assert not any("GROUP_CONCAT" in n for n in notes), notes

    def test_top_limit_claim_present(self, transpiler):
        result = transpiler.transpile(
            "SELECT TOP 5 * FROM t", "tsql", "mysql"
        )
        assert result.success is True, result.error
        assert "LIMIT" in result.target_sql.upper(), result.target_sql
        assert any(
            "TOP" in n and "LIMIT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_top_limit_claim_suppressed_without_target_evidence(
        self, transpiler
    ):
        notes = transpiler._get_compatibility_notes(
            "tsql", "mysql",
            source_sql="SELECT TOP 5 * FROM t",
            final_sql="SELECT TOP 5 * FROM t",
        )
        assert not any("TOP" in n and "LIMIT" in n for n in notes), notes

    def test_getdate_now_claim_suppressed_when_engine_produces_timestamp(
        self, transpiler
    ):
        """The engine really converts GETDATE() to CURRENT_TIMESTAMP(),
        not NOW() (sqlglot consumes GETDATE before the NOW rule fires).
        The claim must fail closed against the actual output."""
        result = transpiler.transpile(
            "SELECT GETDATE() FROM t", "tsql", "mysql"
        )
        assert result.success is True, result.error
        assert "NOW()" not in result.target_sql.upper(), result.target_sql
        assert not any(
            "GETDATE" in n and "NOW()" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_getdate_now_claim_present_with_target_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "tsql", "mysql",
            source_sql="SELECT GETDATE() FROM t",
            final_sql="SELECT NOW() FROM t",
        )
        assert any(
            "GETDATE" in n and "NOW()" in n for n in notes
        ), notes

    def test_no_claims_without_any_source_constructs(self, transpiler):
        result = transpiler.transpile("SELECT 1", "tsql", "mysql")
        assert result.success is True, result.error
        for forbidden in ("STRING_AGG", "TOP", "GETDATE"):
            assert not any(
                forbidden in n for n in result.compatibility_notes
            ), (forbidden, result.compatibility_notes)

    def test_hive_array_map_converted_to_json_claim(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="CREATE TABLE t (tags ARRAY<STRING>)",
            final_sql="CREATE TABLE t (tags JSON)",
        )
        assert any(
            "converted to JSON" in n for n in notes
        ), notes

        notes_without = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="SELECT 1",
            final_sql="SELECT 1",
        )
        assert not any(
            "converted to JSON" in n for n in notes_without
        ), notes_without


# ── B2-3a T5 — B2-3 behaviors must not regress ───────────────────────────────

class TestB23A_T5_B23BehaviorsUnchanged:
    def test_limit_advisory_survives(self, transpiler):
        result = transpiler.transpile(
            "SELECT * FROM t LIMIT 5", "postgres", "oracle"
        )
        assert result.success is True, result.error
        assert any(
            "Oracle uses FETCH FIRST" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_lateral_view_advisory_and_no_false_claim(self, transpiler):
        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "mysql")
        assert result.success is True, result.error
        assert any(
            "may need manual adjustment" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes
        assert not any(
            "converted to UNNEST/JSON_TABLE" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_source_advisories_still_source_based(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="CREATE TABLE x (id INT AUTO_INCREMENT PRIMARY KEY)",
            final_sql="CREATE TABLE x (id SERIAL PRIMARY KEY)",
        )
        assert any(
            "AUTO_INCREMENT" in n and "varies" in n for n in notes
        ), notes


# ── B2-3b — evidence must be SQL-aware (literals/comments are not code) ──────

class TestB23B_SQLAwareEvidence:
    """Construct detection must ignore text inside comments and string
    literals.  A construct spelled only in a comment or a literal is not
    evidence that the source used it or that the final SQL produced it."""

    def test_source_listagg_only_in_literal_no_claim(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql="SELECT 'LISTAGG' AS txt FROM t",
            final_sql="SELECT ARRAY_JOIN(COLLECT_LIST(x), ',') FROM t",
        )
        assert not any("ARRAY_JOIN" in n for n in notes), notes

    def test_source_listagg_only_in_comment_no_claim(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql="SELECT 1 -- LISTAGG(name, ',') WITHIN GROUP (ORDER BY id)",
            final_sql="SELECT ARRAY_JOIN(COLLECT_LIST(x), ',') FROM t",
        )
        assert not any("ARRAY_JOIN" in n for n in notes), notes

    def test_final_array_join_only_in_literal_not_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=LISTAGG_SQL,
            final_sql="SELECT 'ARRAY_JOIN' AS txt FROM t",
        )
        assert not any("ARRAY_JOIN" in n for n in notes), notes

    def test_source_connect_by_only_in_literal_no_claim(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql="SELECT 'CONNECT BY' AS txt FROM t",
            final_sql="WITH RECURSIVE cte AS (SELECT 1) SELECT * FROM cte",
        )
        assert not any("WITH RECURSIVE" in n for n in notes), notes

    def test_final_with_recursive_only_in_literal_not_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql=CONNECT_BY_SQL,
            final_sql="SELECT 'WITH RECURSIVE' AS txt FROM t",
        )
        assert not any("WITH RECURSIVE" in n for n in notes), notes

    def test_source_getdate_only_in_literal_no_claim(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "tsql", "mysql",
            source_sql="SELECT 'GETDATE()' AS txt FROM t",
            final_sql="SELECT NOW() FROM t",
        )
        assert not any(
            "GETDATE" in n and "NOW()" in n for n in notes
        ), notes

    def test_source_lateral_view_only_in_literal_no_advisory(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="SELECT 'LATERAL VIEW' AS txt FROM t",
            final_sql="SELECT 'LATERAL VIEW' AS txt FROM t",
        )
        assert not any(
            "LATERAL VIEW" in n for n in notes
        ), notes

    def test_final_unnest_only_in_literal_not_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "postgres",
            source_sql=LATERAL_VIEW_SQL,
            final_sql="SELECT 'UNNEST' AS txt FROM t",
        )
        assert not any("UNNEST" in n for n in notes), notes

    def test_source_limit_only_in_literal_no_advisory(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "oracle",
            source_sql="SELECT 'LIMIT' AS txt FROM t",
            final_sql="SELECT 1",
        )
        assert not any(
            "Oracle uses FETCH FIRST" in n for n in notes
        ), notes

    def test_real_conversions_still_keep_claims(self, transpiler):
        """Regression anchor: the SQL-aware masking must not break the
        real-conversion claims established in B2-3 / B2-3a."""
        result = transpiler.transpile(LISTAGG_SQL, "oracle", "hive")
        assert "ARRAY_JOIN" in result.target_sql.upper()
        assert any(
            "ARRAY_JOIN" in n for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(CONNECT_BY_SQL, "oracle", "duckdb")
        assert "WITH RECURSIVE" in result.target_sql.upper()
        assert any(
            "WITH RECURSIVE" in n for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "duckdb")
        assert "UNNEST" in result.target_sql.upper()
        assert any(
            "LATERAL VIEW" in n and "UNNEST" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT GROUP_CONCAT(name SEPARATOR ',') FROM users",
            "mysql", "postgres",
        )
        assert "STRING_AGG" in result.target_sql.upper()
        assert any(
            "GROUP_CONCAT" in n and "STRING_AGG" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT IFNULL(a, 0) FROM t", "mysql", "postgres"
        )
        assert any(
            "IFNULL" in n and "COALESCE" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT STRING_AGG(name, ',') FROM users", "postgres", "mysql"
        )
        assert any(
            "STRING_AGG" in n and "GROUP_CONCAT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT TOP 5 * FROM t", "tsql", "mysql"
        )
        assert any(
            "TOP" in n and "LIMIT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

    def test_class_a_advisories_still_retained_for_real_constructs(
        self, transpiler
    ):
        result = transpiler.transpile(
            "SELECT * FROM t LIMIT 5", "postgres", "oracle"
        )
        assert any(
            "Oracle uses FETCH FIRST" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "mysql")
        assert any(
            "may need manual adjustment" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes


# ── B2-3c — identifier substrings are not construct evidence ────────────────

class TestB23C_IdentifierSubstringsAreNotEvidence:
    """Ordinary identifiers that merely contain a construct name
    (LISTAGG_value, limit_count, STRING_AGG_backup, COALESCE_backup,
    UNNEST_helper, …) must not count as source constructs or as
    conversion-result evidence."""

    def test_listagg_identifier_not_source_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql="SELECT LISTAGG_value FROM t",
            final_sql="SELECT ARRAY_JOIN_value FROM t",
        )
        assert not any("ARRAY_JOIN" in n for n in notes), notes

    def test_limit_identifier_not_advisory_trigger(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "oracle",
            source_sql="SELECT limit_count FROM t",
            final_sql="SELECT limit_count FROM t",
        )
        assert not any(
            "Oracle uses FETCH FIRST" in n for n in notes
        ), notes

    def test_string_agg_identifier_not_claim_trigger(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "mysql",
            source_sql="SELECT STRING_AGG_backup FROM t",
            final_sql="SELECT GROUP_CONCAT_backup FROM t",
        )
        assert not any(
            "STRING_AGG" in n and "GROUP_CONCAT" in n for n in notes
        ), notes

    def test_group_concat_identifier_not_claim_trigger(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="SELECT GROUP_CONCAT_backup FROM t",
            final_sql="SELECT STRING_AGG_backup FROM t",
        )
        assert not any(
            "GROUP_CONCAT" in n and "STRING_AGG" in n for n in notes
        ), notes

    def test_coalesce_identifier_not_target_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "mysql", "postgres",
            source_sql="SELECT IFNULL(a, 0) FROM t",
            final_sql="SELECT COALESCE_backup FROM t",
        )
        assert not any(
            "IFNULL" in n and "COALESCE" in n for n in notes
        ), notes

    def test_unnest_identifier_not_target_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "postgres",
            source_sql=LATERAL_VIEW_SQL,
            final_sql="SELECT UNNEST_helper FROM t",
        )
        assert not any("UNNEST" in n for n in notes), notes

    def test_real_constructs_still_detected(self, transpiler):
        """Guard: function-call forms and keyword forms must keep
        matching after the boundary-aware change."""
        result = transpiler.transpile(LISTAGG_SQL, "oracle", "hive")
        assert any(
            "ARRAY_JOIN" in n for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT * FROM t LIMIT 5", "postgres", "oracle"
        )
        assert any(
            "Oracle uses FETCH FIRST" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT IFNULL(a, 0) FROM t", "mysql", "postgres"
        )
        assert any(
            "IFNULL" in n and "COALESCE" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(LATERAL_VIEW_SQL, "hive", "duckdb")
        assert any(
            "UNNEST" in n for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT STRING_AGG(name, ',') FROM users", "postgres", "mysql"
        )
        assert any(
            "STRING_AGG" in n and "GROUP_CONCAT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes


# ── B2-3d — identifier boundaries ($, Unicode, dots) and type context ───────

class TestB23D_IdentifierBoundariesAndConstructSemantics:
    """Construct evidence must respect the full SQL identifier character
    set ($ and Unicode letters) and must not mistake qualified
    references or ordinary identifiers for clauses / types."""

    def test_dollar_identifier_not_limit_clause(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "oracle",
            source_sql="SELECT limit$column FROM t",
            final_sql="SELECT limit$column FROM t",
        )
        assert not any(
            "Oracle uses FETCH FIRST" in n for n in notes
        ), notes

    def test_unicode_adjacent_identifier_not_limit_clause(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "oracle",
            source_sql="SELECT LIMIT列 FROM t",
            final_sql="SELECT LIMIT列 FROM t",
        )
        assert not any(
            "Oracle uses FETCH FIRST" in n for n in notes
        ), notes

    def test_dollar_function_identifier_not_listagg(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "oracle", "hive",
            source_sql="SELECT schema$LISTAGG(x) FROM t",
            final_sql="SELECT ARRAY_JOIN(COLLECT_LIST(x), ',') FROM t",
        )
        assert not any("ARRAY_JOIN" in n for n in notes), notes

    def test_unicode_before_function_name_not_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "mysql",
            source_sql="SELECT 列STRING_AGG(x) FROM t",
            final_sql="SELECT GROUP_CONCAT(x) FROM t",
        )
        assert not any(
            "STRING_AGG" in n and "GROUP_CONCAT" in n for n in notes
        ), notes

    def test_qualified_column_not_limit_clause(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "oracle",
            source_sql="SELECT t.limit FROM t",
            final_sql="SELECT t.limit FROM t",
        )
        assert not any(
            "Oracle uses FETCH FIRST" in n for n in notes
        ), notes

    def test_qualified_column_not_top_clause(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "tsql", "mysql",
            source_sql="SELECT t.TOP FROM t",
            final_sql="SELECT * FROM t LIMIT 5",
        )
        assert not any(
            "TOP" in n and "LIMIT" in n for n in notes
        ), notes

    def test_qualified_column_not_merge_advisory(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "postgres", "mysql",
            source_sql="SELECT t.merge FROM t",
            final_sql="SELECT t.merge FROM t",
        )
        assert not any(
            "MERGE syntax varies" in n for n in notes
        ), notes

    def test_qualified_refs_not_array_to_json_type_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="SELECT t.ARRAY FROM t",
            final_sql="SELECT t.JSON FROM t",
        )
        assert not any("converted to JSON" in n for n in notes), notes

    def test_bare_columns_not_array_to_json_type_evidence(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="SELECT array FROM t",
            final_sql="SELECT json FROM t",
        )
        assert not any("converted to JSON" in n for n in notes), notes

    def test_real_type_constructs_still_detected(self, transpiler):
        notes = transpiler._get_compatibility_notes(
            "hive", "mysql",
            source_sql="CREATE TABLE t (tags ARRAY<STRING>)",
            final_sql="CREATE TABLE t (tags JSON)",
        )
        assert any("converted to JSON" in n for n in notes), notes

    def test_real_clause_and_function_constructs_still_detected(
        self, transpiler
    ):
        result = transpiler.transpile(
            "SELECT * FROM t LIMIT 5", "postgres", "oracle"
        )
        assert any(
            "Oracle uses FETCH FIRST" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(
            "SELECT TOP 5 * FROM t", "tsql", "mysql"
        )
        assert any(
            "TOP" in n and "LIMIT" in n
            for n in result.compatibility_notes
        ), result.compatibility_notes

        result = transpiler.transpile(LISTAGG_SQL, "oracle", "hive")
        assert any(
            "ARRAY_JOIN" in n for n in result.compatibility_notes
        ), result.compatibility_notes
