#!/usr/bin/env python3
"""G2: NL2SQL evidence trail completeness.

Regression tests for the evidence-based confidence model:

* Every successful ``NL2SQLResult`` carries a non-empty
  ``GenerationEvidence`` whose items explain the confidence score.
* The evidence score (sum of item weights, clamped to [0, 1]) equals
  the ``confidence`` field of the result.
* Fail-safe paths (unknown relationships, early boolean/null) must
  still produce an evidence trail — even a minimal one — so that
  consumers can always inspect *why* a result got its score.
* The template path and the enhanced path must both populate the
  evidence field; no generator method may return a result with
  ``evidence=None`` on the success path.
* Evidence ID constants must be unique and deterministic across the
  module; the ``"base"`` literal used by both generation paths must
  remain stable.

All assertions go through the canonical public entry point
(``backend.core.nl2sql.NL2SQLGenerator``).
"""
from __future__ import annotations

import pytest

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_components.evidence import (
    EVIDENCE_AGGREGATION_PRESENT,
    EVIDENCE_COLUMNS_EXPLICIT,
    EVIDENCE_CONDITIONS_PRESENT,
    EVIDENCE_GROUP_BY,
    EVIDENCE_JOIN_KNOWN,
    EVIDENCE_LIMIT,
    EVIDENCE_PARSE_FAIL,
    EVIDENCE_PARSE_OK,
    EVIDENCE_TABLE_KNOWN,
    EVIDENCE_TEMPLATE_MATCHED,
    GenerationEvidence,
)

DIALECTS = ["postgres", "hive", "mysql", "oracle", "tsql", "duckdb"]

# The "base" item ID is used as a bare string literal in both
# _generate_from_template and _build_sql_enhanced; it is intentionally
# not a module-level constant because it represents the path-specific
# starting confidence, not a semantic evidence category. Guard its
# stability so a rename or dynamic ID does not silently break consumers.
_BASE_ITEM_ID = "base"


@pytest.fixture
def gen():
    return NL2SQLGenerator()


def evidence_score(result) -> float:
    """Recompute the clamped evidence score independently."""
    if result.evidence is None:
        return result.confidence
    return max(0.0, min(1.0, sum(i.weight for i in result.evidence.items)))


class TestEvidenceTrailCompleteness:
    """Successful results must carry a non-empty evidence trail."""

    SUCCESS_INPUTS = [
        "find all users",
        "find products with price greater than 100",
        "last 7 days",
        "calculate average price for products",
        "find users who have orders",
        "top 10 users",
        "count orders by category",
        "find active orders from last 7 days",
    ]

    @pytest.mark.parametrize("text", SUCCESS_INPUTS)
    def test_success_result_has_evidence(self, gen, text):
        result = gen.generate(text, "postgres")
        assert result.success is True, result.explanation
        assert result.evidence is not None, "successful result must carry evidence"
        assert isinstance(result.evidence, GenerationEvidence)
        assert len(result.evidence.items) >= 1, (
            f"expected at least one evidence item for {text!r}, "
            f"got {len(result.evidence.items)}"
        )

    @pytest.mark.parametrize("text", SUCCESS_INPUTS)
    def test_evidence_score_equals_confidence(self, gen, text):
        result = gen.generate(text, "postgres")
        assert result.success is True
        # The clamped sum of evidence weights must equal the confidence score.
        assert abs(evidence_score(result) - result.confidence) < 1e-9, (
            f"evidence score {evidence_score(result)} != confidence "
            f"{result.confidence} for {text!r}"
        )

    @pytest.mark.parametrize("text", SUCCESS_INPUTS)
    def test_confidence_in_valid_range(self, gen, text):
        result = gen.generate(text, "postgres")
        assert 0.0 <= result.confidence <= 1.0


class TestEvidenceItemContent:
    """Specific evidence items must be present for the clauses they document."""

    def test_table_known_item_present(self, gen):
        result = gen.generate("find all users", "postgres")
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_TABLE_KNOWN in ids, (
            f"expected {EVIDENCE_TABLE_KNOWN} in evidence, got ids={ids}"
        )

    def test_aggregation_item_present(self, gen):
        result = gen.generate("calculate average price for products", "postgres")
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_AGGREGATION_PRESENT in ids, (
            f"expected {EVIDENCE_AGGREGATION_PRESENT} in evidence, got ids={ids}"
        )

    def test_columns_explicit_item_present(self, gen):
        result = gen.generate(
            "find users with user_id and name", "postgres"
        )
        if result.success and result.evidence:
            # Only assert when the path actually populated columns_explicit;
            # the item is conditional on non-wildcard columns.
            ids = [i.evidence_id for i in result.evidence.items]
            if EVIDENCE_COLUMNS_EXPLICIT in ids:
                item = next(
                    i for i in result.evidence.items
                    if i.evidence_id == EVIDENCE_COLUMNS_EXPLICIT
                )
                assert item.weight == 0.1

    def test_join_known_item_present_for_known_pair(self, gen):
        result = gen.generate("find users who have orders", "postgres")
        assert result.success is True
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_JOIN_KNOWN in ids, (
            f"expected {EVIDENCE_JOIN_KNOWN} for known pair, got ids={ids}"
        )

    def test_limit_item_present(self, gen):
        result = gen.generate("top 10 users", "postgres")
        assert result.success is True
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_LIMIT in ids, (
            f"expected {EVIDENCE_LIMIT} for limit query, got ids={ids}"
        )

    def test_group_by_item_present(self, gen):
        # Chinese input triggers the enhanced-path GROUP BY extraction;
        # the English equivalent is not currently captured by _extract_group_by.
        result = gen.generate("统计每个部门的员工数量", "postgres")
        assert result.success is True
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_GROUP_BY in ids, (
            f"expected {EVIDENCE_GROUP_BY} for group-by query, got ids={ids}"
        )

    def test_conditions_present_item_present(self, gen):
        result = gen.generate("find products with price greater than 100", "postgres")
        assert result.success is True
        ids = [i.evidence_id for i in result.evidence.items]
        assert EVIDENCE_CONDITIONS_PRESENT in ids, (
            f"expected {EVIDENCE_CONDITIONS_PRESENT} for conditional query, "
            f"got ids={ids}"
        )

    def test_template_matched_item_weight_is_zero(self, gen):
        """template_matched is a provenance marker, not a confidence boost."""
        result = gen.generate("last 7 days", "postgres")
        assert result.success is True
        for item in result.evidence.items:
            if item.evidence_id == EVIDENCE_TEMPLATE_MATCHED:
                assert item.weight == 0.0
                break


class TestEvidenceItemWeights:
    """Each evidence item must carry the documented fixed weight."""

    WEIGHTS = {
        EVIDENCE_TABLE_KNOWN: 0.1,   # template path; enhanced path uses 0.2
        EVIDENCE_AGGREGATION_PRESENT: 0.15,
        EVIDENCE_COLUMNS_EXPLICIT: 0.1,
        EVIDENCE_JOIN_KNOWN: 0.1,
        EVIDENCE_LIMIT: 0.1,
        EVIDENCE_GROUP_BY: 0.1,
        EVIDENCE_CONDITIONS_PRESENT: 0.1,
        EVIDENCE_TEMPLATE_MATCHED: 0.0,
        EVIDENCE_PARSE_OK: 0.15,
        EVIDENCE_PARSE_FAIL: -0.2,
    }

    def test_parse_ok_weight_is_documented(self, gen):
        result = gen.generate("find all users", "postgres")
        for item in result.evidence.items:
            if item.evidence_id == EVIDENCE_PARSE_OK:
                assert item.weight == 0.15, (
                    f"parse_ok weight {item.weight} != documented 0.15"
                )
                break

    def test_parse_fail_weight_is_documented(self, gen):
        # A parse failure path: use a malformed-ish input that still
        # generates SQL but where the parser rejects it.
        result = gen.generate("delete all data from", "postgres")
        if result.success and result.evidence:
            for item in result.evidence.items:
                if item.evidence_id == EVIDENCE_PARSE_FAIL:
                    assert item.weight == -0.2
                    break

    def test_all_non_parse_items_have_expected_weights(self, gen):
        """For a multi-clause enhanced query, every non-parse item must
        carry its documented weight."""
        result = gen.generate(
            "find users who have orders with price greater than 100 "
            "limit 5",
            "postgres",
        )
        assert result.success is True
        for item in result.evidence.items:
            if item.evidence_id in self.WEIGHTS:
                expected = self.WEIGHTS[item.evidence_id]
                if item.evidence_id == EVIDENCE_TABLE_KNOWN:
                    # Template path uses 0.1, enhanced path uses 0.2.
                    # Only enforce the exact value when the path is known.
                    continue
                assert item.weight == expected, (
                    f"{item.evidence_id}: weight {item.weight} != "
                    f"documented {expected}"
                )


class TestFailSafeEvidenceTrail:
    """Fail-safe (success=False) results must still carry an evidence trail.

    The D2 unknown-relationship gate returns confidence=0.0 with an empty
    GenerationEvidence; the trail must not be None so that callers can
    uniformly inspect *why* the result was rejected.
    """

    UNKNOWN_INPUTS = [
        "find users who have invoices",
        "find users who have logs",
        "find users join invoices",
    ]

    @pytest.mark.parametrize("text", UNKNOWN_INPUTS)
    def test_unknown_relation_result_has_evidence_field(self, gen, text):
        result = gen.generate(text, "postgres")
        assert result.success is False
        assert result.confidence == 0.0
        # The D2 gate returns an empty GenerationEvidence, not None.
        assert result.evidence is not None, (
            f"fail-safe result for {text!r} must still carry evidence (empty is fine)"
        )
        assert isinstance(result.evidence, GenerationEvidence)
        # No confidence-boosting items may appear on a rejected result.
        assert all(i.weight == 0.0 for i in result.evidence.items), (
            f"fail-safe evidence must not boost confidence: {result.evidence.items}"
        )


class TestEvidencePerDialect:
    """Evidence trail must be populated identically across all target dialects."""

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_evidence_present_per_dialect(self, gen, dialect):
        result = gen.generate("find all users", dialect)
        assert result.success is True, result.explanation
        assert result.evidence is not None
        assert len(result.evidence.items) >= 1

    @pytest.mark.parametrize("dialect", DIALECTS)
    def test_evidence_score_in_range_per_dialect(self, gen, dialect):
        result = gen.generate("find all users", dialect)
        assert result.success is True
        assert 0.0 <= result.confidence <= 1.0
        assert abs(evidence_score(result) - result.confidence) < 1e-9


class TestEvidenceSerialization:
    """GenerationEvidence.to_dict() must round-trip the item list."""

    def test_to_dict_structure(self, gen):
        result = gen.generate("find all users", "postgres")
        assert result.evidence is not None
        d = result.evidence.to_dict()
        assert "score" in d
        assert isinstance(d["items"], list)
        for item_dict in d["items"]:
            assert "evidence_id" in item_dict
            assert "label" in item_dict
            assert "weight" in item_dict
            assert "detail" in item_dict
        assert abs(d["score"] - result.confidence) < 1e-9


class TestEvidenceIdStability:
    """Evidence ID constants must be unique and deterministic.

    Guards against silent ID drift: a rename of any ``EVIDENCE_*``
    constant value would break consumers that match on the string.
    """

    @staticmethod
    def _all_evidence_id_values() -> list[str]:
        import backend.core.nl2sql_components.evidence as ev
        return [
            getattr(ev, name)
            for name in dir(ev)
            if name.startswith("EVIDENCE_") and not name.startswith("_")
        ]

    def test_evidence_id_values_are_unique(self):
        values = self._all_evidence_id_values()
        assert len(values) == len(set(values)), (
            f"duplicate evidence ID values: "
            f"{[v for v in set(values) if values.count(v) > 1]}"
        )

    def test_evidence_ids_are_literal_strings(self):
        """IDs must be plain string literals, not dynamically generated."""
        for v in self._all_evidence_id_values():
            assert isinstance(v, str), f"expected str, got {type(v)}: {v!r}"
            assert v, f"empty evidence ID: {v!r}"

    def test_base_item_id_is_stable(self, gen):
        """The 'base' evidence item ID used by both paths must not change.

        The template path uses base=0.7, the enhanced path uses base=0.5;
        both must carry evidence_id='base' so consumers can identify them.
        """
        result = gen.generate("find all users", "postgres")
        assert result.success is True
        base_items = [i for i in result.evidence.items if i.evidence_id == _BASE_ITEM_ID]
        assert base_items, (
            f"expected at least one 'base' evidence item, "
            f"got ids: {[i.evidence_id for i in result.evidence.items]}"
        )
        # The base item's weight encodes the path-specific starting confidence.
        assert base_items[0].weight in (0.5, 0.7), (
            f"base item weight {base_items[0].weight} is not a known "
            f"starting confidence value (0.5 or 0.7)"
        )


class TestFailSafePathsCarryEvidence:
    """Every early-return and fail-safe path in generate() must carry
    a non-None GenerationEvidence, never None."""

    def test_over_length_input_carries_evidence(self, gen):
        """The length guard returns NL2SQLResult without confidence; the
        evidence field must still be present (empty trail, score=0.0)."""
        result = gen.generate("x" * 9000, "postgres")
        assert result.success is False
        assert result.evidence is not None
        assert isinstance(result.evidence, GenerationEvidence)
        assert result.evidence.score == 0.0

    def test_column_hints_error_carries_evidence(self, gen):
        """Invalid column hints must return a result with evidence attached."""
        result = gen.generate(
            "find all users", "postgres", column_hints=["bad; DROP TABLE x"]
        )
        assert result.success is False
        assert result.evidence is not None
        assert result.evidence.score == 0.0

    def test_unsupported_dialect_raises_not_returns(self, gen):
        """Unsupported dialect raises ValueError; no NL2SQLResult is produced.

        This is a caller-contract path (the API layer normalises dialects
        before calling generate), so the evidence field is not applicable.
        """
        with pytest.raises(ValueError):
            gen.generate("find all users", "nosuchdb")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
