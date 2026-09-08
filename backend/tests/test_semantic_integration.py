"""Regression tests for exposing and applying Semantic IR alongside generated SQL."""

import sqlglot
from sqlglot import exp

from backend.core import (
    And,
    ComparisonPredicate,
    NL2SQLGenerator,
    enrich_result_with_semantic_ir,
    rewrite_result_sql_with_semantic_ir,
)
from backend.core.nl2sql_components.boolean_conditions import extract_boolean_conditions


def test_enrichment_adds_semantic_ir_without_replacing_sql_output():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "find products with price greater than 100 and quantity less than 10",
        "postgres",
    )
    assert result.success
    original_sql = result.sql

    conditions = extract_boolean_conditions("find products with price greater than 100 and quantity less than 10")
    enriched = enrich_result_with_semantic_ir(result, conditions, "postgres")

    assert enriched.sql == original_sql
    semantic = enriched.parsed_elements["semantic_ir"]
    assert semantic["operands"][0]["field"] == "price"
    assert semantic["operands"][0]["operator"] == ">"
    assert isinstance(enriched.parsed_elements["semantic_ir"], dict)


def test_enrichment_can_be_called_directly_with_existing_extraction():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询价格大于100且数量小于10的产品",
        "postgres",
    )
    conditions = extract_boolean_conditions("查询价格大于100且数量小于10的产品")

    enrich_result_with_semantic_ir(result, conditions, "postgres")
    semantic = result.parsed_elements["semantic_ir"]

    assert semantic["operands"][0]["field"] == "price"
    assert semantic["operands"][1]["field"] == "quantity"


def test_enrichment_is_noop_for_empty_conditions():
    generator = NL2SQLGenerator()
    result = generator.generate("find products", "postgres")
    enrich_result_with_semantic_ir(result, [], "postgres")
    assert "semantic_ir" not in result.parsed_elements


def test_generation_keeps_legacy_sql_rewrite_disabled_by_default():
    result = NL2SQLGenerator().generate(
        "find products with price greater than 100 and quantity less than 10",
        "postgres",
    )

    assert result.success
    assert "semantic_ir" in result.parsed_elements
    assert "semantic_ast_rewrite" not in result.parsed_elements


def test_explicit_semantic_where_ast_rewrite_is_supported():
    result = NL2SQLGenerator().generate(
        "find products with price greater than 100 and quantity less than 10",
        "postgres",
    )
    original_sql = result.sql
    conditions = extract_boolean_conditions(
        "find products with price greater than 100 and quantity less than 10"
    )

    rewrite_result_sql_with_semantic_ir(result, conditions, "postgres")

    assert result.parsed_elements["semantic_ast_rewrite"] is True
    assert result.sql != original_sql
    tree = sqlglot.parse_one(result.sql.split("\n", 1)[1], read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    assert isinstance(where.this, exp.And)
    assert {column.name for column in where.this.find_all(exp.Column)} >= {"price", "quantity"}


def test_rewrite_is_a_noop_when_semantic_condition_is_unsupported():
    generator = NL2SQLGenerator()
    result = generator.generate("find products with price greater than 100", "postgres")
    original_sql = result.sql

    rewrite_result_sql_with_semantic_ir(
        result,
        ["DATE_SUB(created_at, 1) > CURRENT_DATE"],
        "postgres",
    )

    assert result.sql == original_sql
    assert result.parsed_elements["semantic_ast_rewrite"] is False


def test_rewrite_preserves_non_where_query_clauses():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "find products with price greater than 100",
        "postgres",
    )
    assert result.success
    header, body = result.sql.split("\n", 1)
    result.sql = f"{header}\n{body}\nORDER BY price DESC\nLIMIT 10"
    original_sql = result.sql
    conditions = ["price > 100"]

    rewrite_result_sql_with_semantic_ir(result, conditions, "postgres")

    assert result.parsed_elements["semantic_ast_rewrite"] is True
    assert "ORDER BY PRICE DESC" in original_sql.upper()
    assert "ORDER BY PRICE DESC" in result.sql.upper()
    assert "LIMIT 10" in result.sql.upper()


def test_manual_rewrite_accepts_structured_boolean_semantics():
    generator = NL2SQLGenerator()
    result = generator.generate("find products with price greater than 100", "postgres")
    semantic = And(
        operands=(
            ComparisonPredicate(field="price", operator=">", value=100),
            ComparisonPredicate(field="quantity", operator="<", value=10),
        )
    )
    result.parsed_elements["semantic_ir"] = semantic.to_dict()

    rewrite_result_sql_with_semantic_ir(
        result,
        ["(price > 100) AND (quantity < 10)"],
        "postgres",
    )
    tree = sqlglot.parse_one(result.sql.split("\n", 1)[1], read="postgres")
    where = tree.find(exp.Where)
    assert isinstance(where.this, exp.And)
    assert {column.name for column in where.this.find_all(exp.Column)} >= {"price", "quantity"}
