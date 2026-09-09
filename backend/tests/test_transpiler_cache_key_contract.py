from backend.core.transpiler import SQLTranspiler


def test_cache_key_separates_validation_mode() -> None:
    transpiler = SQLTranspiler()

    validated = transpiler._cache_key(
        "SELECT 1", "postgres", "mysql", pretty=True, validate=True
    )
    unvalidated = transpiler._cache_key(
        "SELECT 1", "postgres", "mysql", pretty=True, validate=False
    )

    assert validated != unvalidated


def test_cache_key_changes_when_rule_contract_changes() -> None:
    transpiler = SQLTranspiler()
    baseline = transpiler._cache_key(
        "SELECT 1", "postgres", "mysql", pretty=True, validate=True
    )

    rule = transpiler.post_processor.engine.rules[0]
    original_pattern = rule.pattern
    try:
        rule.pattern = original_pattern + "_cache_contract"
        changed = transpiler._cache_key(
            "SELECT 1", "postgres", "mysql", pretty=True, validate=True
        )
    finally:
        rule.pattern = original_pattern

    assert changed != baseline


def test_transpile_does_not_reuse_validated_cache_for_unvalidated_mode() -> None:
    transpiler = SQLTranspiler()
    sql = "SELECT 1"

    validated = transpiler.transpile(
        sql, "postgres", "mysql", pretty=True, validate=True
    )
    unvalidated = transpiler.transpile(
        sql, "postgres", "mysql", pretty=True, validate=False
    )

    assert validated.success is True
    assert unvalidated.success is True
    assert transpiler._cache_key(
        sql, "postgres", "mysql", pretty=True, validate=True
    ) != transpiler._cache_key(
        sql, "postgres", "mysql", pretty=True, validate=False
    )
