"""Semantic regression contracts for cross-dialect SQL conversion.

The existing 12x12 matrix proves conversion and target parseability. This suite
adds semantic contracts for a dialect-neutral subset across all pairs, plus
representative dialect-specific features where equivalence is expected.

Assertions intentionally separate syntax validity, structural equivalence, and
runtime equivalence. AST-based structural checks are not treated as a proof of
runtime equality across database engines.
"""

from dataclasses import dataclass

import pytest
import sqlglot
from sqlglot import exp

from backend.core.parser import SUPPORTED_DIALECTS
from backend.core.semantic_diff import diff_sql_ast
from backend.core.transpiler import SQLTranspiler


@dataclass(frozen=True)
class SemanticCase:
    name: str
    source_dialect: str
    target_dialect: str
    sql: str
    equivalence: str = "structural"


@pytest.fixture(scope="module")
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


COMMON_CASE = "SELECT id, name FROM users WHERE status = 1"


@pytest.mark.parametrize(
    "source,target",
    [(source, target) for source in SUPPORTED_DIALECTS for target in SUPPORTED_DIALECTS],
)
def test_all_supported_pairs_preserve_common_select_semantics(
    transpiler: SQLTranspiler, source: str, target: str
) -> None:
    """Every pair must preserve the meaning of a dialect-neutral SELECT."""
    result = transpiler.transpile(COMMON_CASE, source, target)

    assert result.success, f"Conversion failed for {source} -> {target}: {result.error}"
    assert result.target_sql

    diff = diff_sql_ast(COMMON_CASE, result.target_sql, source, target)
    assert diff.parse_error is None
    assert diff.equivalent, (
        f"Semantic drift for {source} -> {target}: {diff.differences}"
    )


SEMANTIC_CASES = [
    SemanticCase(
        name="mysql_to_postgres_filter_order",
        source_dialect="mysql",
        target_dialect="postgres",
        sql="SELECT id, name FROM users WHERE status = 1 ORDER BY id DESC",
    ),
    SemanticCase(
        name="postgres_to_duckdb_null_predicate",
        source_dialect="postgres",
        target_dialect="duckdb",
        sql="SELECT id FROM users WHERE deleted_at IS NULL",
    ),
    SemanticCase(
        name="tsql_to_hive_top_n",
        source_dialect="tsql",
        target_dialect="hive",
        sql="SELECT TOP 5 id, name FROM users ORDER BY id DESC",
    ),
    SemanticCase(
        name="hive_to_oracle_group_order",
        source_dialect="hive",
        target_dialect="oracle",
        sql=(
            "SELECT department, COUNT(*) AS count FROM employees "
            "GROUP BY department ORDER BY count DESC"
        ),
    ),
]


@pytest.mark.parametrize("case", SEMANTIC_CASES, ids=lambda case: case.name)
def test_representative_semantic_contracts(
    transpiler: SQLTranspiler, case: SemanticCase
) -> None:
    """Representative conversions preserve the expected structural semantics."""
    result = transpiler.transpile(
        case.sql, case.source_dialect, case.target_dialect
    )

    assert result.success, (
        f"Conversion failed for {case.name}: {result.error}"
    )
    assert result.target_sql

    diff = diff_sql_ast(
        case.sql,
        result.target_sql,
        case.source_dialect,
        case.target_dialect,
    )
    assert diff.parse_error is None
    assert diff.equivalent, (
        f"Semantic drift for {case.name}: {diff.differences}"
    )


STRUCTURAL_PROPERTY_CASES = [
    SemanticCase(
        name="mysql_to_postgres_aggregate",
        source_dialect="mysql",
        target_dialect="postgres",
        sql=(
            "SELECT department, COUNT(*) AS count FROM employees "
            "GROUP BY department ORDER BY count DESC"
        ),
    ),
    SemanticCase(
        name="postgres_to_duckdb_null",
        source_dialect="postgres",
        target_dialect="duckdb",
        sql="SELECT id FROM users WHERE deleted_at IS NULL",
    ),
]


def _without_aliases(tree: exp.Expression) -> exp.Expression:
    """Copy an AST while ignoring projection aliases for structural checks."""
    return tree.transform(
        lambda node: node.copy().set("alias", None)
        if isinstance(node, exp.Alias)
        else node.copy()
    )


@pytest.mark.parametrize(
    "case", STRUCTURAL_PROPERTY_CASES, ids=lambda case: case.name
)
def test_structural_properties_are_explicitly_asserted(
    transpiler: SQLTranspiler, case: SemanticCase
) -> None:
    """Aggregate/null examples expose semantic properties independently of formatting."""
    result = transpiler.transpile(
        case.sql, case.source_dialect, case.target_dialect
    )
    assert result.success, result.error
    assert result.target_sql

    source_tree = sqlglot.parse_one(case.sql, read=case.source_dialect)
    target_tree = sqlglot.parse_one(result.target_sql, read=case.target_dialect)

    source_structural = _without_aliases(source_tree)
    target_structural = _without_aliases(target_tree)

    assert {type(node).__name__ for node in source_structural.walk()} == {
        type(node).__name__ for node in target_structural.walk()
    }

    if source_tree.find(exp.Group) is not None:
        assert target_tree.find(exp.Group) is not None
    if source_tree.find(exp.Is) is not None:
        assert target_tree.find(exp.Is) is not None


@pytest.mark.parametrize(
    "source,target,sql",
    [
        (
            "postgres",
            "duckdb",
            "SELECT id FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'",
        ),
        (
            "mysql",
            "postgres",
            "SELECT id FROM users WHERE created_at >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)",
        ),
    ],
)
def test_date_arithmetic_semantics_are_checked_by_ast_shape(
    transpiler: SQLTranspiler, source: str, target: str, sql: str
) -> None:
    """Date arithmetic conversions must retain a date column and interval boundary."""
    result = transpiler.transpile(sql, source, target)
    assert result.success, f"{source} -> {target}: {result.error}"
    assert result.target_sql

    source_tree = sqlglot.parse_one(sql, read=source)
    target_tree = sqlglot.parse_one(result.target_sql, read=target)

    assert list(source_tree.find_all(exp.Column))[0].name == list(
        target_tree.find_all(exp.Column)
    )[0].name
    assert any(isinstance(node, exp.Interval) for node in target_tree.walk()) or any(
        isinstance(node, exp.Literal) and node.is_number
        for node in target_tree.walk()
    )


@pytest.mark.parametrize(
    "sql,source,target",
    [
        (
            "SELECT id, name FROM users WHERE status = 1 AND age >= 18",
            "postgres",
            "mysql",
        ),
        (
            "SELECT id, name FROM users WHERE status = 1 OR age < 18",
            "postgres",
            "duckdb",
        ),
    ],
)
def test_boolean_precedence_contract_is_preserved(
    transpiler: SQLTranspiler, sql: str, source: str, target: str
) -> None:
    """AND/OR predicates must remain represented by the same boolean AST nodes."""
    result = transpiler.transpile(sql, source, target)
    assert result.success, result.error
    assert result.target_sql

    source_tree = sqlglot.parse_one(sql, read=source)
    target_tree = sqlglot.parse_one(result.target_sql, read=target)

    source_booleans = [type(node).__name__ for node in source_tree.walk() if isinstance(node, (exp.And, exp.Or))]
    target_booleans = [type(node).__name__ for node in target_tree.walk() if isinstance(node, (exp.And, exp.Or))]
    assert target_booleans == source_booleans
