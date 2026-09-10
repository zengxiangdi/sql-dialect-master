from backend.core.config import settings
from backend.core.post_processor import PostProcessor
from backend.core.rules import RuleCategory, RuleEngine, TransformRule
from backend.core.transpiler import SQLTranspiler


def _rule(*, name="custom_select_rewrite", enabled=True, priority=50, pattern=r"SELECT 1", replacement="SELECT 2"):
    return TransformRule(
        name=name,
        source="mysql",
        target="postgres",
        pattern=pattern,
        replacement=replacement,
        note="test rule",
        category=RuleCategory.SYNTAX,
        priority=priority,
        enabled=enabled,
    )


def _key(transpiler):
    return transpiler._cache_key("SELECT 1", "mysql", "postgres", False, False)


def test_add_rule_changes_cache_identity():
    engine = RuleEngine([_rule()])
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine)

    before = _key(transpiler)
    engine.add_rule(_rule(name="second_rule", pattern=r"SELECT 3", replacement="SELECT 4"))

    assert _key(transpiler) != before


def test_enable_and_disable_rule_change_cache_identity():
    rule = _rule(enabled=False)
    engine = RuleEngine([rule])
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine)

    disabled_key = _key(transpiler)
    assert engine.enable_rule(rule.name) is True
    enabled_key = _key(transpiler)
    assert enabled_key != disabled_key

    assert engine.disable_rule(rule.name) is True
    assert _key(transpiler) == disabled_key


def test_direct_enabled_mutation_changes_cache_identity():
    rule = _rule()
    engine = RuleEngine([rule])
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine)

    before = _key(transpiler)
    rule.enabled = False

    assert _key(transpiler) != before


def test_direct_rule_field_mutation_changes_cache_identity():
    rule = _rule()
    engine = RuleEngine([rule])
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine)

    baseline = _key(transpiler)

    rule.priority += 1
    assert _key(transpiler) != baseline

    rule.priority -= 1
    rule.pattern = r"SELECT 9"
    assert _key(transpiler) != baseline


def test_direct_rules_list_mutation_changes_cache_identity():
    engine = RuleEngine([_rule()])
    transpiler = SQLTranspiler()
    transpiler.post_processor = PostProcessor(engine)

    before = _key(transpiler)
    engine.rules.append(_rule(name="direct_append", pattern=r"SELECT 5", replacement="SELECT 6"))

    assert _key(transpiler) != before


def test_custom_post_processor_engine_participates_in_cache_identity():
    transpiler = SQLTranspiler()
    engine_a = RuleEngine([_rule(name="engine_a", replacement="SELECT 2")])
    engine_b = RuleEngine([_rule(name="engine_b", replacement="SELECT 3")])

    transpiler.post_processor = PostProcessor(engine_a)
    key_a = _key(transpiler)

    transpiler.post_processor = PostProcessor(engine_b)
    key_b = _key(transpiler)

    assert key_a != key_b


def test_cached_result_cannot_survive_rule_disable(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", False)

    rule = _rule()
    engine = RuleEngine([rule])
    transpiler = SQLTranspiler()
    transpiler._cache_enabled = True
    transpiler._cache.clear()
    transpiler.post_processor = PostProcessor(engine)

    first = transpiler.transpile("SELECT 1", "mysql", "postgres", pretty=False, validate=False)
    assert first.success is True
    assert first.target_sql == "SELECT 2"

    assert engine.disable_rule(rule.name) is True
    second = transpiler.transpile("SELECT 1", "mysql", "postgres", pretty=False, validate=False)

    assert second.success is True
    assert second.target_sql == "SELECT 1"
