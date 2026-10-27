"""P1 Batch 2b2 schema group-label and subject-table contracts."""

import pytest
import sqlglot

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.nl2sql_schema import SchemaContext


def schema_context(*, relationship=True, orders_user_id=True, employees_department=True, users=True):
    tables = [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}]},
        {"name": "employees", "columns": [{"name": "id"}, {"name": "name"}]},
    ]
    if orders_user_id:
        tables[0]["columns"].append({"name": "user_id"})
    if employees_department:
        tables[1]["columns"].append({"name": "department"})
    if users:
        tables.append({"name": "users", "columns": [{"name": "id"}, {"name": "name"}]})
    relationships = []
    if relationship and users and orders_user_id:
        relationships.append({
            "from_table": "orders", "from_column": "user_id",
            "to_table": "users", "to_column": "id",
        })
    return SchemaContext.from_mapping({"tables": tables, "relationships": relationships})


def generate(text, schema=None):
    return NL2SQLGenerator().generate("".join([text]), "postgres", schema=schema)


def executable_sql(result):
    return " ".join(
        line.strip()
        for line in result.sql.splitlines()
        if not line.strip().startswith("--")
    )


def column_label_schema(*columns, departments=False):
    tables = [{
        "name": "employees",
        "columns": [{"name": "id"}, *({"name": column} for column in columns)],
    }]
    if departments:
        tables.append({"name": "departments", "columns": [{"name": "id"}]})
    return SchemaContext.from_mapping({"tables": tables})


@pytest.mark.parametrize("text", [
    "How many orders per user",
    "Show number of orders per user",
    "Count orders per user",
])
def test_orders_per_user_uses_data_fk_group(text):
    result = generate(text, schema_context())
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "FROM orders" in result.sql
    assert "GROUP BY user_id" in result.sql
    assert "JOIN users" not in result.sql


def test_orders_per_user_allows_unique_fk_without_relationship():
    result = generate("How many orders per user", schema_context(relationship=False))
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "GROUP BY user_id" in result.sql


def test_orders_per_user_uses_fk_when_relationship_is_declared_in_reverse():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {
                "from_table": "users",
                "from_column": "id",
                "to_table": "orders",
                "to_column": "user_id",
            },
        ],
    })
    result = generate("How many orders per user", schema)
    assert result.success
    assert "SELECT user_id, COUNT(*) AS count" in result.sql
    assert "FROM orders" in result.sql
    assert "GROUP BY user_id" in result.sql


def reverse_relationship_schema():
    return SchemaContext.from_mapping({
        "tables": [
            {"name": "users", "columns": [{"name": "id"}]},
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}]},
        ],
        "relationships": [
            {
                "from_table": "users",
                "from_column": "id",
                "to_table": "orders",
                "to_column": "user_id",
            },
        ],
    })


@pytest.mark.parametrize("text", [
    "How many users per order",
    "Count users per order",
    "Show number of users per order",
])
def test_reverse_declared_relationship_rejects_users_per_order(text):
    result = generate(text, reverse_relationship_schema())
    assert result.success is False
    assert result.sql is None


def test_nonstandard_forward_fk_rejects_group_label():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "buyer_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {
                "from_table": "orders",
                "from_column": "buyer_id",
                "to_table": "users",
                "to_column": "id",
            },
        ],
    })
    result = generate("How many orders per user", schema)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "How many users per order",
    "Count users per order",
    "Show number of users per order",
])
def test_reverse_group_label_relationship_fails_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


def test_employees_per_department_uses_subject_column():
    result = generate("Count employees per department", schema_context())
    assert result.success
    assert "SELECT department, COUNT(*) AS count" in result.sql
    assert "FROM employees" in result.sql
    assert "GROUP BY department" in result.sql


@pytest.mark.parametrize("schema", [
    schema_context(users=False),
    schema_context(orders_user_id=False),
])
def test_orders_per_user_without_label_table_or_fk_fails_closed(schema):
    result = generate("How many orders per user", schema)
    assert result.success is False
    assert result.sql is None


def test_orders_per_user_with_multiple_relationships_fails_closed():
    schema = schema_context()
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "buyer_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
            {"from_table": "orders", "from_column": "buyer_id", "to_table": "users", "to_column": "id"},
        ],
    })
    result = generate("How many orders per user", schema)
    assert result.success is False
    assert result.sql is None


def test_employees_per_department_without_department_column_fails_closed():
    result = generate("Count employees per department", schema_context(employees_department=False))
    assert result.success is False
    assert result.sql is None


def test_orders_per_department_without_column_or_relationship_fails_closed():
    result = generate("Show number of orders per department", schema_context())
    assert result.success is False
    assert result.sql is None


def test_unknown_group_label_fails_closed():
    result = generate("How many orders per unknown", schema_context())
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "Show number of orders per user_id",
    "Count orders by user_id",
    "Count orders grouped by user_id",
])
def test_batch_two_a_explicit_columns_remain_unchanged(text):
    result = generate(text, schema_context())
    assert result.success
    assert "user_id" in result.sql
    assert "GROUP BY user_id" in result.sql


def test_count_only_and_ordering_do_not_gain_grouping():
    count = generate("Show number of orders", schema_context())
    ordered = generate("Show users ordered by name", schema_context())
    assert count.success and "COUNT(*) AS count" in count.sql and "GROUP BY" not in count.sql
    assert ordered.success and "GROUP BY" not in ordered.sql


@pytest.mark.parametrize("text", [
    "统计每个部门员工数量",
    "每个部门的员工数量",
    "统计每个部门的员工数量",
    "统计各个部门员工数量",
])
def test_chinese_department_group_uses_employee_column(text):
    result = generate(text, schema_context())
    assert result.success, result.explanation
    assert result.schema_used is True
    assert executable_sql(result) == (
        "SELECT department, COUNT(*) AS count FROM employees GROUP BY department"
    )


@pytest.mark.parametrize("text", [
    "统计每个用户订单数量",
    "每个用户的订单数量",
    "每个用户订单数量",
    "各个用户的订单数量",
    "统计每位用户的订单数量",
])
def test_chinese_user_group_uses_orders_fk(text):
    result = generate(text, schema_context())
    assert result.success, result.explanation
    assert result.schema_used is True
    assert executable_sql(result) == (
        "SELECT user_id, COUNT(*) AS count FROM orders GROUP BY user_id"
    )


def test_chinese_department_column_takes_priority_over_department_table():
    result = generate(
        "统计每个部门员工数量", column_label_schema("department", departments=True)
    )
    assert result.success, result.explanation
    assert executable_sql(result) == (
        "SELECT department, COUNT(*) AS count FROM employees GROUP BY department"
    )


@pytest.mark.parametrize("label,column", [
    ("部门", "department"),
    ("部门", "dept"),
    ("状态", "status"),
    ("类型", "type"),
    ("分类", "category"),
    ("日期", "date"),
    ("地区", "region"),
    ("区域", "region"),
    ("品牌", "brand"),
    ("级别", "level"),
    ("优先级", "priority"),
])
def test_chinese_group_column_aliases(label, column):
    result = generate(f"统计每个{label}员工数量", column_label_schema(column))
    assert result.success, result.explanation
    assert executable_sql(result) == (
        f"SELECT {column}, COUNT(*) AS count FROM employees GROUP BY {column}"
    )


def test_chinese_department_with_both_column_aliases_fails_closed():
    result = generate("统计每个部门员工数量", column_label_schema("department", "dept"))
    assert result.success is False
    assert result.sql is None


def test_chinese_unknown_table_outside_consumed_label_still_fails_closed():
    result = generate("统计每个部门的员工数量和部门", column_label_schema("department"))
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("metric,aggregate", [("平均", "AVG"), ("总和", "SUM")])
def test_chinese_group_label_keeps_aggregate_metric_separate(metric, aggregate):
    result = generate(
        f"每个部门的员工价格{metric}", column_label_schema("department", "price")
    )
    assert result.success, result.explanation
    assert executable_sql(result) == (
        f"SELECT department, {aggregate}(price) FROM employees GROUP BY department"
    )


def test_chinese_department_relationship_uses_employee_fk():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "employees", "columns": [{"name": "id"}, {"name": "department_id"}]},
            {"name": "departments", "columns": [{"name": "id"}]},
        ],
        "relationships": [{
            "from_table": "employees", "from_column": "department_id",
            "to_table": "departments", "to_column": "id",
        }],
    })
    result = generate("统计每个部门员工数量", schema)
    assert result.success, result.explanation
    assert executable_sql(result) == (
        "SELECT department_id, COUNT(*) AS count FROM employees GROUP BY department_id"
    )


@pytest.mark.parametrize("schema", [
    schema_context(relationship=False),
    reverse_relationship_schema(),
])
def test_chinese_user_group_allows_unique_direct_fk(schema):
    result = generate("统计每个用户订单数量", schema)
    assert result.success, result.explanation
    assert executable_sql(result) == (
        "SELECT user_id, COUNT(*) AS count FROM orders GROUP BY user_id"
    )


@pytest.mark.parametrize("schema", [
    schema_context(users=False),
    schema_context(orders_user_id=False),
])
def test_chinese_user_group_without_label_table_or_fk_fails_closed(schema):
    result = generate("统计每个用户订单数量", schema)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("text", [
    "统计每位员工的订单数量",
    "每位员工订单数量",
    "每个部门的订单数量",
    "每个区域",
    "每个未知label",
    "每个区域订单数量",
    "每个未知label订单数量",
    "统计每个用户订单和员工数量",
    "统计每个用户订单数量和每个部门员工数量",
])
def test_chinese_unresolved_or_ambiguous_group_labels_fail_closed(text):
    result = generate(text, schema_context())
    assert result.success is False
    assert result.sql is None


def test_chinese_user_group_with_multiple_relationships_fails_closed():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "user_id"}, {"name": "users_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [
            {"from_table": "orders", "from_column": "user_id", "to_table": "users", "to_column": "id"},
            {"from_table": "orders", "from_column": "users_id", "to_table": "users", "to_column": "id"},
        ],
    })
    result = generate("统计每个用户订单数量", schema)
    assert result.success is False
    assert result.sql is None


def test_chinese_user_group_rejects_nonstandard_forward_fk():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}, {"name": "buyer_id"}]},
            {"name": "users", "columns": [{"name": "id"}]},
        ],
        "relationships": [{
            "from_table": "orders", "from_column": "buyer_id",
            "to_table": "users", "to_column": "id",
        }],
    })
    result = generate("统计每个用户订单数量", schema)
    assert result.success is False
    assert result.sql is None


@pytest.mark.parametrize("schema", [schema_context(), reverse_relationship_schema()])
def test_chinese_reverse_entity_group_rejects_primary_key_relationship(schema):
    result = generate("每个订单用户数量", schema)
    assert result.success is False
    assert result.sql is None


def test_chinese_group_fk_uses_qualified_table_and_canonical_column_case():
    schema = SchemaContext.from_mapping({
        "tables": [
            {"name": "public.orders", "columns": [{"name": "id"}, {"name": "USER_ID"}]},
            {"name": "public.users", "columns": [{"name": "id"}]},
        ],
        "relationships": [{
            "from_table": "public.orders", "from_column": "USER_ID",
            "to_table": "public.users", "to_column": "id",
        }],
    })
    result = generate("统计每个用户订单数量", schema)
    assert result.success, result.explanation
    assert executable_sql(result) == (
        "SELECT USER_ID, COUNT(*) AS count FROM public.orders GROUP BY USER_ID"
    )


@pytest.mark.parametrize("text,table,column,expected", [
    ("统计订单数量", "orders", "id", "SELECT COUNT(*) AS count FROM orders"),
    ("统计库存数量", "inventory", "quantity", "SELECT SUM(quantity) FROM inventory"),
    ("统计购买数量", "orders", "quantity", "SELECT SUM(quantity) FROM orders"),
])
def test_chinese_group_labels_preserve_count_and_quantity_metrics(text, table, column, expected):
    schema = SchemaContext.from_mapping({
        "tables": [{"name": table, "columns": [{"name": column}]}],
    })
    result = generate(text, schema)
    assert result.success, result.explanation
    assert executable_sql(result) == expected


@pytest.mark.parametrize("text", [
    "How many orders per user",
    "Count employees per department",
    "Show number of orders per user_id",
])
def test_no_schema_outputs_remain_current(text):
    first = generate(text)
    second = generate(text)
    assert first.success == second.success
    assert first.sql == second.sql
    assert first.schema_used is False


@pytest.mark.parametrize("text,expected", [
    (
        "统计每个部门员工数量",
        "SELECT COUNT(*) AS count FROM departments "
        "INNER JOIN employees ON departments.id = employees.dept_id GROUP BY quantity",
    ),
    (
        "每个部门的员工数量",
        "SELECT department, COUNT(*) AS count FROM departments "
        "INNER JOIN employees ON departments.id = employees.dept_id GROUP BY department",
    ),
    (
        "统计每个部门的员工数量",
        "SELECT department, COUNT(*) AS count FROM departments "
        "INNER JOIN employees ON departments.id = employees.dept_id GROUP BY department",
    ),
    (
        "统计每个用户订单数量",
        "SELECT COUNT(*) AS count FROM users "
        "INNER JOIN orders ON users.id = orders.user_id GROUP BY quantity",
    ),
    (
        "每个用户的订单数量",
        "SELECT user_id, COUNT(*) AS count FROM users "
        "INNER JOIN orders ON users.id = orders.user_id GROUP BY user_id",
    ),
    (
        "每个用户订单数量",
        "SELECT COUNT(*) AS count FROM users "
        "INNER JOIN orders ON users.id = orders.user_id GROUP BY quantity",
    ),
    (
        "统计各个部门员工数量",
        "SELECT COUNT(*) AS count FROM departments "
        "INNER JOIN employees ON departments.id = employees.dept_id GROUP BY quantity",
    ),
    ("统计每位员工的订单数量", None),
    ("每个部门的订单数量", None),
    ("每个区域订单数量", "SELECT COUNT(*) AS count FROM orders GROUP BY quantity"),
    ("每个未知label订单数量", "SELECT COUNT(*) AS count FROM orders GROUP BY quantity"),
])
def test_chinese_group_label_no_schema_outputs_match_existing_sql(text, expected):
    result = generate(text)
    assert result.schema_used is False
    if expected is None:
        assert result.success is False
        assert result.sql is None
    else:
        assert result.success
        assert executable_sql(result) == expected


@pytest.mark.parametrize("dialect", [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
])
@pytest.mark.parametrize("text", [
    "How many orders per user",
    "统计每个部门员工数量",
    "每个用户的订单数量",
])
def test_group_label_sql_parses_in_all_dialects(dialect, text):
    result = NL2SQLGenerator().generate(text, dialect, schema=schema_context())
    assert result.success
    assert sqlglot.parse_one(result.sql, read=dialect) is not None


@pytest.mark.parametrize("text", [
    "How many orders per user",
    "统计每个部门员工数量",
    "每个用户的订单数量",
])
def test_group_label_results_are_deterministic(text):
    first = generate(text, schema_context())
    second = generate(text, schema_context())
    assert first.success and second.success
    assert first.sql == second.sql
