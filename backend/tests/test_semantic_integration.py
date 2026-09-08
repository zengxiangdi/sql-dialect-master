"""Regression tests for exposing Semantic IR alongside generated SQL."""

from backend.core import NL2SQLGenerator, ComparisonPredicate, And, enrich_result_with_semantic_ir
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
