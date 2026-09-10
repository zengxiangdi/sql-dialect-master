from backend.core.rules import RuleEngine, TransformRule
from backend.core.post_processor import PostProcessor
from backend.core.transpiler import SQLTranspiler


def _make_rule(name="ifnull_rule"):
    return TransformRule(
        name=name,
        source="mysql",
        target="postgres",
        pattern=r"IFNULL\(([^,]+),\s*([^)]+)\)",
        replacement=r"COALESCE(\1, \2)",
        note="test rule",
    )


def _make_transpiler(engine=None):
    transpiler = SQLTranspiler()
    if engine is not None:
        transpiler.post_processor = PostProcessor(engine=engine)
    return transpiler


def test_unchanged_rules_reuse_rule_version_hash(monkeypatch):
    transpiler = _make_transpiler(RuleEngine([_make_rule()]))
    calls = 0
    import backend.core.transpiler as transpiler_module

    original_sha256 = transpiler_module.hashlib.sha256

    def counting_sha256(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_sha256(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.hashlib, "sha256", counting_sha256)

    first = transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)
    second = transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)

    assert first == second
    assert calls == 1


def test_direct_rule_mutation_invalidates_cached_rule_version(monkeypatch):
    rule = _make_rule()
    transpiler = _make_transpiler(RuleEngine([rule]))
    calls = 0
    import backend.core.transpiler as transpiler_module

    original_sha256 = transpiler_module.hashlib.sha256

    def counting_sha256(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_sha256(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.hashlib, "sha256", counting_sha256)

    first = transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)
    rule.priority += 1
    second = transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)

    assert first != second
    assert calls == 2


def test_direct_engine_rules_list_mutation_invalidates_cached_rule_version(monkeypatch):
    engine = RuleEngine([_make_rule("rule_a")])
    transpiler = _make_transpiler(engine)
    calls = 0
    import backend.core.transpiler as transpiler_module

    original_sha256 = transpiler_module.hashlib.sha256

    def counting_sha256(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_sha256(*args, **kwargs)

    monkeypatch.setattr(transpiler_module.hashlib, "sha256", counting_sha256)

    transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)
    engine.rules.append(_make_rule("rule_b"))
    transpiler._cache_key("SELECT 1", "mysql", "postgres", False, True)

    assert calls == 2


def test_custom_post_processors_have_independent_rule_snapshots(monkeypatch):
    first_engine = RuleEngine([_make_rule("rule_a")])
    second_engine = RuleEngine([_make_rule("rule_b")])
    first = _make_transpiler(first_engine)
    second = _make_transpiler(second_engine)

    first_key = first._cache_key("SELECT 1", "mysql", "postgres", False, True)
    second_key = second._cache_key("SELECT 1", "mysql", "postgres", False, True)

    assert first_key != second_key

    first_engine.rules[0].enabled = False
    assert first._cache_key("SELECT 1", "mysql", "postgres", False, True) != first_key
    assert second._cache_key("SELECT 1", "mysql", "postgres", False, True) == second_key
