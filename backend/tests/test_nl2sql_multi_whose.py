"""AND-only whose lists for schema-aware unique counts."""

import itertools
import sqlite3
from contextlib import closing

import pytest
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.tests.test_nl2sql_composite_unique_count import schema as composite_schema
from backend.tests.test_nl2sql_p13_whose import USERS_SCHEMA
from backend.tests.test_nl2sql_path_filter_ownership import (
    DIALECTS,
    onehop_schema,
    twohop_schema,
)
from backend.tests.test_nl2sql_unique_count import make_schema


def generate(text, schema=None, dialect="postgres"):
    return NL2SQLGenerator().generate(text, dialect, schema=schema)


def assert_failed(result):
    assert result.success is False
    assert result.sql is None
    assert result.confidence == 0.0


def statements(result):
    assert result.success, result.explanation
    return sqlglot.parse_one(result.sql, read="postgres")


@pytest.mark.parametrize("explicit", list(itertools.product([False, True], repeat=2)))
@pytest.mark.parametrize("connector", [" and ", " AND ", ", ", "，"])
@pytest.mark.parametrize("zero", [False, True])
def test_three_predicates_accept_every_optional_whose_combination(explicit, connector, zero):
    predicates = ["users.status is active", "orders.status is paid", "products.status is enabled"]
    text = "count distinct products per user whose " + predicates[0]
    for prefix, predicate in zip(explicit, predicates[1:]):
        text += connector + ("whose " if prefix else "") + predicate
    if zero:
        text += " including zero"
    result = generate(text, twohop_schema())

    assert result.success, result.explanation
    expected = ["users.status = 'active'", "orders.status = 'paid'", "products.status = 'enabled'"]
    if zero:
        baseline, counts = result.sql.split(") AS b\nLEFT JOIN (", 1)
        assert expected[0] in baseline
        assert expected[1] not in baseline and expected[2] not in baseline
        assert all(predicate in counts for predicate in expected)
        assert counts.index(expected[0]) < counts.index(expected[1]) < counts.index(expected[2])
        assert "WHERE" not in result.sql.rsplit(") AS c ON", 1)[1]
    else:
        assert all(result.sql.count(predicate) == 1 for predicate in expected)
        assert result.sql.index(expected[0]) < result.sql.index(expected[1]) < result.sql.index(expected[2])
    assert "条件: 3个" in result.explanation


@pytest.mark.parametrize("predicates", [
    "users.status is active and products.status is enabled",
    "users.status is active and orders.status is paid",
    "products.status is enabled and orders.status is paid",
    "users.id > 0 and users.tenant_id is 1",
])
def test_two_predicates_support_owner_pairs_and_same_owner(predicates):
    result = generate("count distinct products per user whose " + predicates, twohop_schema())
    assert result.success, result.explanation
    assert "条件: 2个" in result.explanation


@pytest.mark.parametrize("zero", [False, True])
def test_target_first_input_is_subject_first_and_path_source_order_is_stable(zero):
    text = (
        "count distinct products per user whose products.status is enabled "
        "and users.status is active and orders.status is paid"
        + (" including zero" if zero else "")
    )
    result = generate(text, twohop_schema())
    assert result.success, result.explanation
    counts = result.sql.split(") AS b\nLEFT JOIN (", 1)[-1]
    assert counts.index("users.status = 'active'") < counts.index("products.status = 'enabled'")
    assert counts.index("products.status = 'enabled'") < counts.index("orders.status = 'paid'")


@pytest.mark.parametrize("connector", [" and ", ", ", "，"])
@pytest.mark.parametrize("suffix,fragment", [
    ("including zero", "LEFT JOIN"),
    ("ordered by count desc", "ORDER BY COUNT(*) DESC"),
    ("limit 5", "LIMIT 5"),
    ("first 5", "LIMIT 5"),
    ("only 5", "LIMIT 5"),
    ("前5", "LIMIT 5"),
    ("5条", "LIMIT 5"),
    ("5个", "LIMIT 5"),
    ("5行", "LIMIT 5"),
    ("5 rows", "LIMIT 5"),
    ("top 10 ordered by count desc", "LIMIT 10"),
    ("ordered by count desc top 10", "LIMIT 10"),
])
@pytest.mark.parametrize("count", [1, 2, 3])
def test_connector_prefers_structural_suffix_after_any_predicate(count, connector, suffix, fragment):
    predicates = ["users.status is active", "orders.status is paid", "products.status is enabled"]
    text = "count distinct products per user whose " + " and ".join(predicates[:count]) + connector + suffix
    result = generate(text, twohop_schema())
    assert result.success, result.explanation
    assert fragment in result.sql
    assert f"条件: {count}个" in result.explanation


@pytest.mark.parametrize("suffix", [
    "top 10", "top 10 ordered by users.id desc", "ordered by users.id desc top 10",
    "ordered by count desc first 5", "ordered by count desc only 5",
    "ordered by count desc 前5", "ordered by count desc 5条",
    "ordered by count desc 5个", "ordered by count desc 5行",
    "ordered by count desc 5 rows", "first 5 ordered by count desc",
])
def test_structural_suffix_scope_still_fails_closed(suffix):
    assert_failed(generate(
        "count distinct products per user whose users.status is active "
        "and products.status is enabled, " + suffix,
        twohop_schema(),
    ))


@pytest.mark.parametrize("values", [
    ("desc", "max"), ("'order by count desc'", "'limit 5'"),
    ("'top 10'", "'first 3'"), ("sort", "sorted"), ("'前5'", "'5 rows'"),
    ("limit", "desc"), ("max", "limit"),
])
@pytest.mark.parametrize("zero", [False, True])
def test_second_and_third_value_tokens_are_masked_everywhere(values, zero):
    text = (
        f"count distinct products per user whose users.status is active "
        f"and orders.status is {values[0]} and products.status is {values[1]}"
        + (" including zero" if zero else "")
    )
    result = generate(text, twohop_schema())
    tree = statements(result)
    assert not list(tree.find_all(exp.Order))
    assert not list(tree.find_all(exp.Limit))
    assert "条件: 3个" in result.explanation
    if zero:
        baseline = result.sql.split(") AS b\nLEFT JOIN (", 1)[0]
        assert "orders.status" not in baseline and "products.status" not in baseline


@pytest.mark.parametrize("suffix,limit", [
    ("ordered by count desc limit 2", 2),
    ("ordered by count desc top 10", 10),
    ("top 10 ordered by count desc", 10),
])
@pytest.mark.parametrize("zero", [False, True])
def test_real_order_and_limit_survive_all_filter_span_masking(suffix, limit, zero):
    result = generate(
        "count distinct products per user whose users.status is 'desc' "
        "and orders.status is 'top 5' and products.status is 'limit 7'"
        + (" including zero" if zero else "") + " " + suffix,
        twohop_schema(),
    )
    tree = statements(result)
    assert len(list(tree.find_all(exp.Order))) == 1
    assert int(tree.args["limit"].expression.this) == limit
    assert len(list(tree.find_all(exp.Limit))) == 1


@pytest.mark.parametrize("value", [
    "'and whose'", "'a,b，c'", "'(and whose, order by count desc limit 5)'", '"O\'Reilly and whose"',
])
def test_quoted_connector_parenthesis_and_clause_words_are_literal_values(value):
    result = generate(
        f"count distinct products per user whose products.status is {value} "
        "and users.status is active",
        twohop_schema(),
    )
    tree = statements(result)
    assert not list(tree.find_all(exp.Order)) and not list(tree.find_all(exp.Limit))
    assert "条件: 2个" in result.explanation


def test_comments_containing_connectors_and_ordering_do_not_split_predicates():
    result = generate(
        "count distinct products per user whose users.status is active "
        "/* whose products.status is bad or (nested) order by count desc limit 5 */ "
        "and products.status is enabled",
        twohop_schema(),
    )
    tree = statements(result)
    assert not list(tree.find_all(exp.Order)) and not list(tree.find_all(exp.Limit))
    assert "bad" not in result.sql and "enabled" in result.sql


@pytest.mark.parametrize("predicates", [
    "users.status is active users.id is 1",
    "users.status is active whose products.id is 1",
    "users.status is active and garbage",
    "users.status is active,",
    "users.status is active and",
    "users.status is active and products.status in (active)",
    "users.status is active or products.tenant_id is 1",
    "(users.status is active and products.tenant_id is 1)",
    "users.status is active and (products.tenant_id is 1)",
    "users.status is active and products.status is lower(active)",
    "users.status is 'unclosed",
    "users.status is active and products.status is",
    "users.status is active and products.status is 'unclosed",
    "users.status is active and products.id is 1 and orders.id is 1 and users.id is 1",
    "users.status is active and tenant_id is 1",
    "users.status is active and shipments.status is paid",
    "users.status is active and products.unknown is 1",
])
def test_invalid_or_unsupported_predicate_anywhere_fails_entire_request(predicates):
    assert_failed(generate("count distinct products per user whose " + predicates, twohop_schema()))


@pytest.mark.parametrize("tail", [
    "and including zero and products.id is 1",
    "and including zero, products.id is 1",
    "and including zero whose products.id is 1",
    "and including zero, whose products.id is 1",
    "and including zero garbage",
    "and limit 5 and products.id is 1",
    "and limit 5, products.id is 1",
    "and limit 5 whose products.id is 1",
    "and limit 5, whose products.id is 1",
    "and limit 5 garbage",
    "and first 5 and products.id is 1",
    "and ordered by count desc and products.id is 1",
    "and ordered by count desc limit 5 whose products.id is 1",
])
@pytest.mark.parametrize("predicate_count", [1, 2])
def test_structural_suffix_cannot_hide_a_following_filter_or_garbage(tail, predicate_count):
    predicates = "users.status is active"
    if predicate_count == 2:
        predicates += " and orders.status is paid"
    assert_failed(generate(
        "count distinct products per user whose " + predicates + " " + tail,
        twohop_schema(),
    ))


@pytest.mark.parametrize("predicates", [
    "users.status is active and users.status equals active",
    "products.tenant_id is 1 and products.tenant_id = 1.0",
    "products.tenant_id = 01.00 and products.tenant_id equals 1",
    "users.status is active and USERS.STATUS = 'active'",
    "users.status is null and users.status IS NULL",
    "products.status is not disabled and products.status <> 'disabled'",
    "orders.product_id is 1 and product_id = 1.0",
    'products.status is "active" and products.status equals \'active\'',
    "products.status is 张三 and products.status is '张三'",
    "products.status is   not disabled and products.status != 'disabled'",
    "products.status is   not null and products.status isn't NULL",
])
def test_resolved_canonical_path_duplicates_fail(predicates):
    assert_failed(generate("count distinct products per user whose " + predicates, twohop_schema()))


@pytest.mark.parametrize("predicates", [
    "products.status is Active and products.status is active",
    "products.tenant_id is 1 and orders.tenant_id is 1",
    "products.id > 1 and products.id >= 1",
    "products.id is 1 and products.id is 2",
])
def test_different_literals_operators_and_owners_are_not_duplicates(predicates):
    result = generate("count distinct products per user whose " + predicates, twohop_schema())
    assert result.success, result.explanation
    assert "条件: 2个" in result.explanation


def test_unique_operator_whitespace_is_normalized_for_path_predicate():
    result = generate(
        "count distinct products per user whose products.status is   not disabled "
        "and users.status is active",
        twohop_schema(),
    )
    assert result.success, result.explanation
    assert "products.status != 'disabled'" in result.sql
    assert "users.status = 'active'" in result.sql


@pytest.mark.parametrize("predicates", [
    "status is active and orders.status equals 'active'",
    "amount = 1 and orders.amount is 1.0",
    "status is null and orders.status IS NULL",
    "status is not disabled and orders.status != 'disabled'",
    "status is   not disabled and orders.status != 'disabled'",
])
def test_selected_table_duplicate_resolution_includes_qualified_and_unqualified(predicates):
    assert_failed(generate("count distinct orders whose " + predicates, make_schema(primary_key=["id"])))


def test_unique_operator_whitespace_is_normalized_for_selected_predicate():
    result = generate(
        "count distinct orders whose status is   not disabled and amount > 1",
        make_schema(primary_key=["id"]),
    )
    assert result.success, result.explanation
    assert "status != 'disabled'" in result.sql
    assert "amount > 1" in result.sql


@pytest.mark.parametrize("context,base", [
    (make_schema(primary_key=["id"]), "count distinct orders per user"),
    (make_schema(primary_key=["id"]), "count distinct orders"),
    (composite_schema(primary_key=["tenant_id", "id"]), "count distinct orders per user"),
    (composite_schema(primary_key=["tenant_id", "id"]), "count distinct orders"),
])
def test_selected_flat_single_and_scalar_three_predicates(context, base):
    result = generate(base + " whose status is active and amount > 1, orders.id > 0 limit 2", context)
    tree = statements(result)
    assert "status = 'active'" in result.sql and "amount > 1" in result.sql and "id > 0" in result.sql
    assert "条件: 3个" in result.explanation
    assert int(tree.args["limit"].expression.this) == 2
    assert not list(tree.find_all(exp.Order))


@pytest.mark.parametrize("context", [
    make_schema(primary_key=["id"]),
    composite_schema(primary_key=["tenant_id", "id"]),
])
def test_selected_grouped_count_ordering_masks_every_predicate(context):
    result = generate(
        "count distinct orders per user whose status is 'top 8' and amount > 1 "
        "and orders.id > 0 ordered by count desc limit 2",
        context,
    )
    tree = statements(result)
    assert int(tree.args["limit"].expression.this) == 2
    assert len(list(tree.find_all(exp.Order))) == 1
    assert "条件: 3个" in result.explanation


@pytest.mark.parametrize("zero", [False, True])
@pytest.mark.parametrize("composite", [False, True])
def test_onehop_multi_whose_preserves_shape_specific_ownership(zero, composite):
    context = onehop_schema(composite_subject=composite)
    if zero or composite:
        predicates = "users.status is active and orders.status is paid"
    else:
        predicates = "orders.status is paid and orders.id > 0"
    result = generate(
        "count distinct orders per user whose " + predicates + (" including zero" if zero else ""),
        context,
    )
    assert result.success, result.explanation
    if zero:
        assert "LEFT JOIN" in result.sql
    elif not composite:
        assert "COUNT(DISTINCT id)" in result.sql and "_distinct_targets" not in result.sql
    assert "条件: 2个" in result.explanation


@pytest.mark.parametrize("base,context", [
    ("count distinct orders", make_schema(primary_key=["id"])),
    ("count distinct orders", composite_schema(primary_key=["tenant_id", "id"])),
])
@pytest.mark.parametrize("suffix", ["ordered by count desc", "top 10"])
def test_scalar_multifilter_still_rejects_structural_ordering_and_top(base, context, suffix):
    assert_failed(generate(base + " whose status is active and amount > 1 " + suffix, context))


@pytest.mark.parametrize("zero", [False, True])
def test_path_ordinary_where_remains_unsupported_with_multiple_whose(zero):
    assert_failed(generate(
        "count distinct products per user whose users.status is active "
        "and products.status is enabled where orders.id > 0" + (" including zero" if zero else ""),
        twohop_schema(),
    ))


@pytest.mark.parametrize("zero", [False, True])
@pytest.mark.parametrize("owner", ["users", "orders", "products"])
def test_path_filter_preserves_multiline_literals(owner: str, zero: bool) -> None:
    value = "grade = A\r\n-- grade <= B"
    result = generate(
        f"count distinct products per user whose {owner}.status is '{value}'"
        + (" including zero" if zero else ""),
        twohop_schema(),
    )

    assert result.success and result.sql is not None, result.explanation
    tree = sqlglot.parse_one(result.sql, read="postgres")
    values = [literal.this for literal in tree.find_all(exp.Literal) if literal.is_string]
    assert values == [value] * (2 if zero and owner == "users" else 1)


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [("", [(1, 1, 1)]), (" including zero", [(1, 1, 1), (1, 3, 0)])],
)
def test_path_count_matches_original_subject_literal(suffix: str, expected: list[tuple[int, int, int]]) -> None:
    result = generate(
        "count distinct products per user whose users.status is 'grade = A'" + suffix,
        twohop_schema(),
    )

    assert result.success and result.sql is not None, result.explanation
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(
            """
            CREATE TABLE users(tenant_id INTEGER, id INTEGER, status TEXT);
            CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, product_id INTEGER);
            CREATE TABLE products(tenant_id INTEGER, id INTEGER);
            INSERT INTO users VALUES (1, 1, 'grade = A'), (1, 2, 'users.grade = A'), (1, 3, 'grade = A');
            INSERT INTO orders VALUES (1, 10, 1, 10), (1, 11, 2, 10);
            INSERT INTO products VALUES (1, 10);
            """
        )
        assert sorted(connection.execute(result.sql).fetchall()) == expected


@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
@pytest.mark.parametrize("zero", [False, True])
def test_runtime_all_filters_and_zero_subject_population(engine, zero):
    result = generate(
        "count distinct products per user whose products.status is enabled "
        "and users.status is active and orders.status is paid"
        + (" including zero" if zero else "") + " ordered by count desc, users.id asc limit 10",
        twohop_schema(),
    )
    assert result.success, result.explanation
    connection = sqlite3.connect(":memory:") if engine == "sqlite" else pytest.importorskip("duckdb").connect()
    try:
        for statement in (
            "CREATE TABLE users(tenant_id INTEGER, id INTEGER, status TEXT)",
            "CREATE TABLE orders(tenant_id INTEGER, id INTEGER, user_id INTEGER, product_id INTEGER, status TEXT)",
            "CREATE TABLE products(tenant_id INTEGER, id INTEGER, status TEXT)",
            "INSERT INTO users VALUES (1,1,'active'),(1,2,'active'),(1,3,'inactive'),(1,4,'active'),(2,1,'active'),(NULL,7,'active')",
            "INSERT INTO orders VALUES (1,10,1,10,'paid'),(1,11,1,10,'paid'),(1,12,1,11,'paid'),(1,13,2,10,'unpaid'),(1,14,3,10,'paid'),(2,15,1,10,'paid'),(1,16,1,NULL,'paid')",
            "INSERT INTO products VALUES (1,10,'enabled'),(1,11,'disabled'),(2,10,'enabled'),(1,NULL,'enabled')",
        ):
            connection.execute(statement)
        expected = [(1, 1, 1), (2, 1, 1)]
        if zero:
            expected += [(1, 2, 0), (1, 4, 0)]
        assert connection.execute(result.sql.split("\n", 1)[1]).fetchall() == expected
    finally:
        connection.close()


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("zero", [False, True])
def test_multi_whose_is_parseable_in_all_twelve_dialects(dialect, zero):
    result = generate(
        "count distinct products per user whose products.status is enabled "
        "and users.status is active and orders.status is paid"
        + (" including zero" if zero else "") + " ordered by count desc limit 5",
        twohop_schema(), dialect,
    )
    assert result.success, result.explanation
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


def test_multi_whose_sql_explanation_and_evidence_are_deterministic():
    text = "count distinct products per user whose products.status is enabled and users.status is active and orders.status is paid including zero ordered by count desc limit 5"
    first, second = generate(text, twohop_schema()), generate(text, twohop_schema())
    assert first.success and second.success
    assert first.sql == second.sql
    assert first.explanation == second.explanation
    assert first.evidence == second.evidence


def test_general_projection_keeps_legacy_one_whose_and_condition_order():
    result = generate("find users whose nickname is bob and status is active", USERS_SCHEMA)
    assert result.success
    assert "WHERE status = 'active' AND nickname = 'bob'" in result.sql
    multiple = generate("find users whose nickname is bob and whose price > 10", USERS_SCHEMA)
    assert_failed(multiple)


@pytest.mark.parametrize("text", [
    "show user names whose nickname is bob and whose status is active",
    "average price of users whose nickname is bob and whose status is active",
    "find users whose price > 1 and whose status is active",
])
def test_general_projection_and_aggregation_do_not_enable_multi_whose(text):
    assert_failed(generate(text, USERS_SCHEMA))


def test_no_schema_keeps_legacy_sql():
    result = generate("count distinct orders per user")
    assert result.success and result.schema_used is False
    assert "SELECT DISTINCT user_id, COUNT(*) AS count" in result.sql
    assert "GROUP BY user_id" in result.sql
