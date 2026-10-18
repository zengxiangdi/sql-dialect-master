"""Public contract tests for :class:`backend.core.type_mapping.TypeMapper`.

These tests intentionally exercise the mapper through its public methods.  The
bundled mapping file is the contract under test, so assertions focus on stable
status fields and result shape rather than implementation details.
"""

import pytest

from backend.core.type_mapping import TypeMapper


@pytest.fixture()
def mapper() -> TypeMapper:
    return TypeMapper()


def test_parameterized_types_and_aliases_are_normalized(mapper: TypeMapper) -> None:
    varchar = mapper.map_type(" VARCHAR2(2000) ", "oracle", "postgres")
    assert varchar["success"] is True
    assert varchar["precision"] == 2000
    assert varchar["source_type"] == "VARCHAR2(n)"
    assert varchar["target_type"] == "VARCHAR(n)"

    nvarchar = mapper.map_type("NVARCHAR(MAX)", "tsql", "postgres")
    assert nvarchar["success"] is True
    assert nvarchar["precision"] == "MAX"

    empty = mapper.map_type("CHAR()", "mysql", "postgres")
    assert empty["success"] is True
    assert empty["precision"] is None

    literal_precision = mapper.map_type("VARCHAR(foo)", "mysql", "postgres")
    assert literal_precision["precision"] == "FOO"

    alias = mapper.map_type("INTEGER", "postgres", "mysql")
    assert alias["success"] is True

    unknown_parameter = mapper.map_type("NO_SUCH_TYPE(10)", "mysql", "postgres")
    assert unknown_parameter["mapping_status"] == "unknown_type"


def test_map_type_reports_each_failure_state(mapper: TypeMapper) -> None:
    unknown_dialect = mapper.map_type("VARCHAR", "mysql", "no_such_dialect")
    assert unknown_dialect["mapping_status"] == "unknown_dialect"
    assert "no_such_dialect" in unknown_dialect["error"]

    unknown_type = mapper.map_type("NO_SUCH_TYPE", "mysql", "postgres")
    assert unknown_type["mapping_status"] == "unknown_type"
    assert unknown_type["success"] is False

    # The bundled catalog has complete cells; injected partial mappings in
    # test_b3_1_type_mapper_contract.py cover source/target N/A states.


def test_catalog_queries_return_expected_shapes(mapper: TypeMapper) -> None:
    dialect_types = mapper.get_dialect_types("POSTGRES")
    assert len(dialect_types) == len(mapper.mappings)
    assert dialect_types["VARCHAR"] == "VARCHAR(n)"

    comparison = mapper.compare_types("varchar(40)")
    assert comparison["type"] == "VARCHAR"
    assert comparison["dialects"]["postgres"] == "VARCHAR(n)"
    assert comparison["availability"]["coverage"] == "12/12"
    assert mapper.compare_types("missing")["error"] == "Type missing not found"

    all_types = mapper.get_all_types()
    assert len(all_types) == 39
    assert "VARCHAR" in all_types

    filtered = mapper.get_matrix(source="mysql", target="postgres")
    assert filtered["VARCHAR"]["source"] == "VARCHAR(n)"
    assert filtered["VARCHAR"]["target"] == "VARCHAR(n)"
    assert filtered["VARCHAR"]["category"] == "String Types"
    assert set(mapper.get_matrix()) == set(mapper.mappings)


def test_category_and_stats_queries(mapper: TypeMapper) -> None:
    assert mapper.get_type_category("varchar") == "String Types"
    assert mapper.get_type_category("unknown") is None
    assert "VARCHAR" in mapper.get_types_by_category("String Types")
    assert mapper.get_types_by_category("does-not-exist") == []

    stats = mapper.get_stats()
    assert stats["total_types"] == len(mapper.mappings)
    assert stats["total_dialects"] == 12
    assert stats["precision_warnings"] == len(mapper.precision_warnings)
    assert stats["dialect_coverage"]["postgres"] == len(mapper.mappings)
    warnings = mapper.get_precision_warnings()
    assert warnings == mapper.precision_warnings
    assert warnings is not mapper.precision_warnings


def test_compatible_types_and_conversion_path(mapper: TypeMapper) -> None:
    alternatives = mapper.find_compatible_types("VARCHAR", "postgres")
    assert alternatives
    assert all(item["category"] == "String Types" for item in alternatives)
    assert all(item["type"] != "VARCHAR" for item in alternatives)
    assert mapper.find_compatible_types("UNKNOWN", "postgres") == []

    path = mapper.get_conversion_path("VARCHAR", "mysql", "postgres")
    assert path["mapping"]["mapping_status"] == "mapped"
    assert isinstance(path["suggestions"], list)
    assert isinstance(path["alternatives"], list)
    assert path["category"] == "String Types"


def test_reverse_lookup_and_compatibility_matrix(mapper: TypeMapper) -> None:
    source_matches = mapper.find_source_type("VARCHAR(n)", "postgres")
    assert source_matches
    assert source_matches[0]["target_syntax"] == "VARCHAR(n)"
    assert source_matches[0]["exact_match"] is True
    assert mapper.find_source_type("NO SUCH TYPE", "postgres") == []

    matrix = mapper.get_type_compatibility_matrix("VARCHAR")
    assert set(matrix) == set(mapper.DIALECTS)
    assert matrix["mysql"]["mysql"] is True
    assert matrix["mysql"]["postgres"] is True
    assert mapper.get_type_compatibility_matrix("missing")["error"] == (
        "Type missing not found"
    )


@pytest.mark.parametrize(
    ("type_name", "source_syntax", "target_syntax", "expected"),
    [
        ("VARCHAR", "VARCHAR", "TEXT", True),
        ("DECIMAL", "DECIMAL(10,2)", "NUMERIC(10,2)", False),
        ("TIMESTAMP", "TIMESTAMP(6)", "DATETIME(6)", False),
        ("INT", "INT", "BIGINT", True),
    ],
)
def test_compatibility_heuristics(
    mapper: TypeMapper,
    type_name: str,
    source_syntax: str,
    target_syntax: str,
    expected: bool,
) -> None:
    assert mapper._is_compatible_conversion(type_name, source_syntax, target_syntax) is expected


def test_precision_and_type_specific_warnings(mapper: TypeMapper) -> None:
    oracle_default = mapper.map_type("VARCHAR2(4001)", "oracle", "postgres")
    assert any("MAX_STRING_SIZE" in warning for warning in oracle_default["warnings"])

    oracle_extended = mapper.map_type("VARCHAR2(32768)", "oracle", "postgres")
    assert any("CLOB" in warning for warning in oracle_extended["warnings"])

    tsql_nvarchar = mapper.map_type("NVARCHAR(4001)", "tsql", "postgres")
    assert any("NVARCHAR" in warning and "4000" in warning for warning in tsql_nvarchar["warnings"])

    tsql_varchar = mapper.map_type("VARCHAR(8001)", "mysql", "tsql")
    assert any("8000" in warning for warning in tsql_varchar["warnings"])

    mysql_row_limit = mapper.map_type("VARCHAR(21846)", "postgres", "mysql")
    assert any("row size" in warning for warning in mysql_row_limit["warnings"])

    target_oracle = mapper.map_type("VARCHAR(32768)", "mysql", "oracle")
    assert any("Target Oracle" in warning and "CLOB" in warning for warning in target_oracle["warnings"])

    max_oracle = mapper.map_type("VARCHAR(MAX)", "tsql", "oracle")
    assert any("unbounded" in warning for warning in max_oracle["warnings"])
    max_mysql = mapper.map_type("VARCHAR(MAX)", "tsql", "mysql")
    assert any("MEDIUMTEXT" in warning for warning in max_mysql["warnings"])

    array_warning = mapper.map_type("ARRAY", "postgres", "mysql")
    assert any("stored as JSON" in warning for warning in array_warning["warnings"])

    uuid_warning = mapper.map_type("UUID", "postgres", "mysql")
    assert any("CHAR(36)" in warning for warning in uuid_warning["warnings"])

    assert any("VARIANT" in warning for warning in mapper.map_type("JSON", "postgres", "snowflake")["warnings"])
    assert any("STRING" in warning for warning in mapper.map_type("JSON", "postgres", "hive")["warnings"])
    assert any("precision loss" in warning for warning in mapper.map_type("TIMESTAMP", "oracle", "mysql")["warnings"])
    assert any("numeric" in warning for warning in mapper.map_type("BOOLEAN", "postgres", "mysql")["warnings"])


def test_suggest_type_adds_target_specific_recommendations(mapper: TypeMapper) -> None:
    varchar = mapper.suggest_type("VARCHAR(5000)", "mysql", "oracle")
    assert any("MAX_STRING_SIZE" in suggestion for suggestion in varchar["suggestions"])

    decimal = mapper.suggest_type("DECIMAL", "mysql", "postgres")
    assert any("precision" in suggestion.lower() for suggestion in decimal["suggestions"])

    timestamp = mapper.suggest_type("TIMESTAMP", "mysql", "postgres")
    assert any("timezone" in suggestion.lower() for suggestion in timestamp["suggestions"])

    array = mapper.suggest_type("ARRAY", "postgres", "mysql")
    assert any("JSON" in suggestion for suggestion in array["suggestions"])

    json_variant = mapper.suggest_type("JSON", "postgres", "snowflake")
    assert any("VARIANT" in suggestion for suggestion in json_variant["suggestions"])
    uuid = mapper.suggest_type("UUID", "postgres", "oracle")
    assert any("CHAR(36)" in suggestion for suggestion in uuid["suggestions"])
    text = mapper.suggest_type("TEXT", "postgres", "oracle")
    assert any("CLOB" in suggestion for suggestion in text["suggestions"])
    serial = mapper.suggest_type("SERIAL", "postgres", "mysql")
    assert any("Auto-increment" in suggestion for suggestion in serial["suggestions"])

