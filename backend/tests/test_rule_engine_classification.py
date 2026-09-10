"""Regression tests for Phase E2: rule safety classification."""
import pytest

from backend.core.rules import TRANSFORM_RULES, RuleSafety


class TestRuleSafetyClassification:
    """Verify that each rule has a clear safety classification."""

    def test_all_rules_have_safety_classification(self):
        for rule in TRANSFORM_RULES:
            assert rule.safety is not None
            assert rule.safety in (RuleSafety.STRUCTURED, RuleSafety.BOUNDED_REGEX, RuleSafety.LEGACY_REGEX)

    def test_structured_rules_have_function_name_and_replacement(self):
        for rule in TRANSFORM_RULES:
            if rule.safety == RuleSafety.STRUCTURED:
                assert rule.function_name is not None
                assert rule.structured_replacement is not None

    def test_structured_rules_use_scanner(self):
        """Structured rules should be safe for nested function arguments."""
        sql = "SELECT IFNULL(COALESCE(a, b), c) FROM users"
        for rule in TRANSFORM_RULES:
            if rule.safety == RuleSafety.STRUCTURED and "IFNULL" in rule.name:
                result, applied = rule.apply(sql)
                assert applied
                assert "COALESCE(COALESCE(a, b), c)" in result

    def test_legacy_rules_still_work(self):
        """Legacy regex rules must still produce correct output."""
        sql = "SELECT GETDATE() FROM t"
        for rule in TRANSFORM_RULES:
            if rule.safety == RuleSafety.LEGACY_REGEX and "getdate" in rule.name and rule.target == "mysql":
                result, applied = rule.apply(sql)
                assert applied
                assert "NOW()" in result

    def test_no_duplicate_rule_names(self):
        names = [r.name for r in TRANSFORM_RULES]
        assert len(names) == len(set(names)), "Duplicate rule names detected"

    def test_classification_counts(self):
        counts = {s: sum(1 for r in TRANSFORM_RULES if r.safety == s) for s in RuleSafety}
        total = sum(counts.values())
        assert total == len(TRANSFORM_RULES)
        # At minimum we should have some of each type
        assert counts[RuleSafety.STRUCTURED] > 0
        assert counts[RuleSafety.LEGACY_REGEX] > 0
        assert counts[RuleSafety.BOUNDED_REGEX] > 0
