"""Contract tests for the public FunctionEncyclopedia lookup APIs."""

import pytest

from backend.core.functions_lookup import FunctionEncyclopedia


@pytest.fixture()
def encyclopedia() -> FunctionEncyclopedia:
    return FunctionEncyclopedia()


def test_exact_lookup_and_dialect_syntax(encyclopedia: FunctionEncyclopedia) -> None:
    function = encyclopedia.get_function("concat")
    assert function["name"] == "CONCAT"
    assert encyclopedia.get_function("DOES_NOT_EXIST") is None
    assert encyclopedia.get_dialect_syntax("CONCAT", "MYSQL") == "CONCAT(s1, s2, ...)"
    assert encyclopedia.get_dialect_syntax("DOES_NOT_EXIST", "mysql") is None


def test_compare_dialects_default_and_subset(encyclopedia: FunctionEncyclopedia) -> None:
    comparison = encyclopedia.compare_dialects("LENGTH")
    assert comparison["name"] == "LENGTH"
    assert set(comparison["dialects"]) == {
        "hive", "mysql", "oracle", "tsql", "postgres", "spark",
        "trino", "snowflake", "redshift", "clickhouse", "duckdb", "databricks",
    }
    assert comparison["availability"]["coverage"] == "12/12"

    subset = encyclopedia.compare_dialects("LENGTH", ["mysql", "tsql", "missing"])
    assert subset["dialects"] == {
        "mysql": "LENGTH(str) or CHAR_LENGTH(str)",
        "tsql": "LEN(str)",
        "missing": "N/A",
    }
    assert subset["availability"]["supported"] == ["mysql", "tsql"]
    assert subset["availability"]["not_supported"] == ["missing"]
    assert subset["availability"]["coverage"] == "2/3"
    assert encyclopedia.compare_dialects("MISSING")["error"] == "Function MISSING not found"


def test_categories_and_statistics(encyclopedia: FunctionEncyclopedia) -> None:
    categories = encyclopedia.get_all_categories()
    names = {category["name"] for category in categories}
    assert names == set(encyclopedia.CATEGORIES)
    assert all(category["count"] > 0 and category["icon"] for category in categories)
    assert encyclopedia.list_by_category("STRING")
    assert encyclopedia.list_by_category("missing") == []

    stats = encyclopedia.get_stats()
    assert stats["total_functions"] == 298
    assert stats["categories"] == 11
    assert stats["dialects_covered"] == 12
    assert stats["top_categories"][0] == ("string", 59)
    assert stats["dialect_coverage"]["postgres"] > 0


def test_find_equivalent_supported_unknown_and_unsupported(encyclopedia: FunctionEncyclopedia) -> None:
    supported = encyclopedia.find_equivalent("CONCAT", "mysql", "postgres")
    assert supported["supported_in_target"] is True
    assert supported["target_syntax"]
    assert supported["semantic_status"] == "supported-but-different"

    unknown_semantics = encyclopedia.find_equivalent("ROW_NUMBER", "mysql", "postgres")
    assert unknown_semantics["supported_in_target"] is True
    assert unknown_semantics["semantic_status"] == "unknown"

    unsupported = encyclopedia.find_equivalent("ARRAY_CONTAINS", "hive", "redshift")
    assert unsupported["supported_in_target"] is False
    assert unsupported["target_syntax"] is None
    assert encyclopedia.find_equivalent("ARRAY_CONTAINS", "redshift", "hive") is None
    assert encyclopedia.find_equivalent("MISSING", "mysql", "postgres") is None


def test_dialect_function_listing(encyclopedia: FunctionEncyclopedia) -> None:
    postgres = encyclopedia.get_functions_by_dialect("POSTGRES")
    assert postgres
    concat = next(item for item in postgres if item["name"] == "CONCAT")
    assert concat["category"] == "string"
    assert "description" in concat and "parameters" in concat
    assert encyclopedia.get_functions_by_dialect("missing") == []


def test_search_by_description_and_search_boundaries(encyclopedia: FunctionEncyclopedia) -> None:
    description = encyclopedia.search_by_description("concatenate", limit=5)
    assert any(item["name"] == "CONCAT" for item in description)
    assert encyclopedia.search_by_description("no matching phrase") == []
    assert encyclopedia.search_by_description("function", limit=0) == []

    exact = encyclopedia.search("concat", limit=1)
    assert exact[0]["name"] == "CONCAT"
    assert encyclopedia.search("concat", limit=0) == []
    assert encyclopedia.search("zzzz-no-matching-function") == []
    assert encyclopedia.search("", limit=3) and len(encyclopedia.search("", limit=3)) == 3
    date_results = encyclopedia.search("date", limit=10, category="DATE")
    assert date_results
    assert all(item["category"] == "date" for item in date_results)
    assert encyclopedia.search("date", category="missing") == []


def test_function_alternatives_and_semantic_metadata(encyclopedia: FunctionEncyclopedia) -> None:
    alternatives = encyclopedia.get_function_alternatives("ARRAY_CONTAINS", "redshift")
    assert alternatives
    assert len(alternatives) <= 5
    assert all({"name", "syntax", "description", "similarity"} <= item.keys() for item in alternatives)
    assert all(item["similarity"] >= 0 for item in alternatives)
    assert encyclopedia.get_function_alternatives("MISSING", "mysql") == []

    semantics = encyclopedia.resolve_function_semantics("LENGTH", "mysql", "oracle")
    assert semantics["status"] == "supported-but-different"
    assert semantics["equivalent"] is False
    unknown = encyclopedia.resolve_function_semantics("MISSING", "mysql", "oracle")
    assert unknown["status"] == "unknown"

