"""B2-2 — rule cache signature must cover every behavior-affecting field.

``TransformRule`` carries four fields that change what a rule actually
does but were historically absent from the cache signature
(``_rule_cache_state`` / ``_build_rule_cache_payload``):

- ``function_name``           — routes the rule through the scanner-backed
  structured rewrite instead of the plain regex path
- ``structured_replacement``  — argument-aware replacement template
- ``structured_replacer``     — callable that computes the replacement
- ``full_sql_rewriter``       — callable that rewrites the whole SQL

Two rules that differ only in one of these fields produce different
transpile output, so a cache key that ignores them returns a stale
result after the rule set is swapped.

Cache scope (confirmed in ``SQLTranspiler.__init__``): the cache is an
in-memory, per-instance TTL cache — no cross-process persistence.  The
callable identity used for the payload is therefore process-local by
design and is documented as such.
"""
from __future__ import annotations

from backend.core.rules import RuleCategory, RuleEngine, TransformRule
from backend.core.post_processor import PostProcessor
from backend.core.transpiler import SQLTranspiler


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_rule(**overrides):
    """A baseline FOOCALL rule; override any behavior-affecting field."""
    fields = dict(
        name="test_foocall",
        source="postgres",
        target="mysql",
        pattern=r"FOOCALL\s*\((\w+)\)",
        replacement="",
        note="Converted FOOCALL",
        category=RuleCategory.FUNCTION,
        priority=50,
        enabled=True,
        function_name="FOOCALL",
        structured_replacement="CONCAT_A({0})",
    )
    fields.update(overrides)
    return TransformRule(**fields)


def _make_transpiler(*rules) -> SQLTranspiler:
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine=RuleEngine(list(rules)))
    transpiler._cache_enabled = True
    return transpiler


def _make_replacer(prefix: str):
    """Factory producing callables with the SAME __qualname__ but
    different behavior and different object identity.

    Two replacers from this factory share the qualname
    ``_make_replacer.<locals>._replacer`` — so a qualname-only identity
    could never distinguish them.
    """

    def _replacer(args: str, original: str) -> str:
        return prefix + original

    return _replacer


def _make_rewriter(prefix: str):
    """Factory producing whole-SQL rewriters with the same qualname but
    different behavior and identity."""

    def _rewriter(sql: str):
        return sql.replace("FOOCALL", prefix + "REWRITTEN"), True

    return _rewriter


# ── T1 — structured string fields change the version ─────────────────────────

class TestT1StructuredStringFieldsChangeVersion:
    def test_function_name_change_changes_version(self):
        before = _make_transpiler(_make_rule(function_name="FOOCALL"))
        before_version = before._rule_cache_version()

        after = _make_transpiler(_make_rule(function_name="FOOOTHER"))
        after_version = after._rule_cache_version()

        assert before_version != after_version, (
            "function_name change must change the rule cache version"
        )

    def test_function_name_presence_change_changes_version(self):
        before = _make_transpiler(_make_rule(function_name=None))
        after = _make_transpiler(_make_rule(function_name="FOOCALL"))
        assert before._rule_cache_version() != after._rule_cache_version()

    def test_structured_replacement_change_changes_version(self):
        before = _make_transpiler(_make_rule(structured_replacement="CONCAT_A({0})"))
        after = _make_transpiler(_make_rule(structured_replacement="CONCAT_B({0})"))
        assert before._rule_cache_version() != after._rule_cache_version(), (
            "structured_replacement change must change the rule cache version"
        )

    def test_structured_replacement_presence_change_changes_version(self):
        before = _make_transpiler(_make_rule(structured_replacement=None))
        after = _make_transpiler(_make_rule(structured_replacement="CONCAT_A({0})"))
        assert before._rule_cache_version() != after._rule_cache_version()


# ── T2 — callable replacement changes the version ────────────────────────────

class TestT2CallableReplacementChangesVersion:
    def test_structured_replacer_replacement_changes_version(self):
        replacer_a = _make_replacer("A:")
        replacer_b = _make_replacer("B:")
        # The two callables share a qualname — a qualname-only identity
        # would not distinguish them.
        assert replacer_a.__qualname__ == replacer_b.__qualname__
        assert replacer_a is not replacer_b

        before = _make_transpiler(
            _make_rule(structured_replacement=None, structured_replacer=replacer_a)
        )
        after = _make_transpiler(
            _make_rule(structured_replacement=None, structured_replacer=replacer_b)
        )
        assert before._rule_cache_version() != after._rule_cache_version(), (
            "replacing structured_replacer with a different callable must "
            "change the rule cache version"
        )

    def test_structured_replacer_presence_change_changes_version(self):
        replacer = _make_replacer("A:")
        before = _make_transpiler(
            _make_rule(structured_replacement=None, structured_replacer=None)
        )
        after = _make_transpiler(
            _make_rule(structured_replacement=None, structured_replacer=replacer)
        )
        assert before._rule_cache_version() != after._rule_cache_version()

    def test_full_sql_rewriter_replacement_changes_version(self):
        rewriter_a = _make_rewriter("A_")
        rewriter_b = _make_rewriter("B_")
        assert rewriter_a.__qualname__ == rewriter_b.__qualname__
        assert rewriter_a is not rewriter_b

        before = _make_transpiler(
            _make_rule(
                structured_replacement=None,
                structured_replacer=None,
                full_sql_rewriter=rewriter_a,
            )
        )
        after = _make_transpiler(
            _make_rule(
                structured_replacement=None,
                structured_replacer=None,
                full_sql_rewriter=rewriter_b,
            )
        )
        assert before._rule_cache_version() != after._rule_cache_version(), (
            "replacing full_sql_rewriter with a different callable must "
            "change the rule cache version"
        )

    def test_full_sql_rewriter_presence_change_changes_version(self):
        rewriter = _make_rewriter("A_")
        before = _make_transpiler(
            _make_rule(
                structured_replacement=None,
                structured_replacer=None,
                full_sql_rewriter=None,
            )
        )
        after = _make_transpiler(
            _make_rule(
                structured_replacement=None,
                structured_replacer=None,
                full_sql_rewriter=rewriter,
            )
        )
        assert before._rule_cache_version() != after._rule_cache_version()


# ── T3 — real transpile() must not return a stale cached result ──────────────

class TestT3RealTranspileNoStaleCache:
    def test_structured_replacement_swap_returns_fresh_result(self):
        """Two rules identical in every legacy signature field but with
        different ``structured_replacement`` must produce different
        transpile output for the same input — the second call must not
        hit the cached result of the first."""
        sql = "SELECT FOOCALL(x) FROM t"

        rule_a = _make_rule(structured_replacement="CONCAT_A({0})")
        rule_b = _make_rule(structured_replacement="CONCAT_B({0})")

        transpiler = _make_transpiler(rule_a)
        first = transpiler.transpile(sql, "postgres", "mysql")
        assert first.success is True, first.error
        first_version = transpiler._rule_cache_version()
        assert "CONCAT_A" in (first.target_sql or ""), first.target_sql

        # Swap the rule set in the SAME instance; SQL, dialects, and all
        # other cache parameters stay identical.
        transpiler.post_processor = PostProcessor(
            engine=RuleEngine([rule_b])
        )
        second = transpiler.transpile(sql, "postgres", "mysql")
        second_version = transpiler._rule_cache_version()

        assert first_version != second_version, (
            "rule set swap must change the rule cache version"
        )
        assert "CONCAT_B" in (second.target_sql or ""), (
            f"stale cached result returned: {second.target_sql!r}"
        )
        assert "CONCAT_A" not in (second.target_sql or ""), (
            f"stale cached result returned: {second.target_sql!r}"
        )

    def test_function_name_swap_returns_fresh_result(self):
        """Same as above but the behavior-affecting difference is
        ``function_name`` (structured vs legacy regex path).  All
        legacy signature fields — including ``replacement`` — are
        identical between the two rules."""
        sql = "SELECT FOOCALL(x) FROM t"

        # Both rules share pattern and replacement; rule_structured
        # routes through the scanner-backed structured path, rule_regex
        # through the plain regex path.
        rule_structured = _make_rule(
            function_name="FOOCALL",
            structured_replacement="CONCAT_A({0})",
            replacement=r"CONCAT_LEGACY(\1)",
        )
        rule_regex = _make_rule(
            function_name=None,
            structured_replacement=None,
            replacement=r"CONCAT_LEGACY(\1)",
        )

        transpiler = _make_transpiler(rule_structured)
        first = transpiler.transpile(sql, "postgres", "mysql")
        assert "CONCAT_A" in (first.target_sql or ""), first.target_sql
        first_version = transpiler._rule_cache_version()

        transpiler.post_processor = PostProcessor(engine=RuleEngine([rule_regex]))
        second = transpiler.transpile(sql, "postgres", "mysql")

        assert first_version != transpiler._rule_cache_version(), (
            "function_name swap must change the rule cache version"
        )
        assert "CONCAT_A" not in (second.target_sql or ""), (
            f"stale cached result returned: {second.target_sql!r}"
        )


# ── T4 — version stability under an unchanged rule set ───────────────────────

class TestT4VersionStability:
    def test_unchanged_rules_keep_stable_version(self):
        transpiler = _make_transpiler(_make_rule())
        first = transpiler._rule_cache_version()
        assert transpiler._rule_cache_version() == first
        assert transpiler._rule_cache_version() == first

    def test_version_unchanged_after_equivalent_reassignment(self):
        """Replacing the engine with an equivalent rule set (same field
        values, same callable object) keeps the version stable."""
        replacer = _make_replacer("A:")
        rule = _make_rule(structured_replacement=None, structured_replacer=replacer)
        transpiler = _make_transpiler(rule)
        first = transpiler._rule_cache_version()

        transpiler.post_processor = PostProcessor(engine=RuleEngine([_make_rule(
            structured_replacement=None, structured_replacer=replacer,
        )]))
        assert transpiler._rule_cache_version() == first, (
            "equivalent rule reassignment must not change the version"
        )
