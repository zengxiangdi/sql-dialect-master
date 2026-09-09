import pytest

from backend.core.function_semantics import FunctionSemanticRegistry


@pytest.fixture()
def registry():
    return FunctionSemanticRegistry()


@pytest.mark.parametrize(
    "function,source,target,expected_status",
    [
        ("DATEDIFF", "mysql", "tsql", "supported-but-different"),
        ("DATEDIFF", "mysql", "postgres", "supported-but-different"),
        ("DATE_FORMAT", "mysql", "postgres", "supported-but-different"),
        ("LENGTH", "mysql", "oracle", "supported-but-different"),
        ("CONCAT", "mysql", "postgres", "supported-but-different"),
        ("GET_JSON_OBJECT", "hive", "postgres", "supported-but-different"),
        ("COLLECT_LIST", "spark", "postgres", "supported-but-different"),
    ],
)
def test_syntax_presence_does_not_prove_equivalence(
    registry, function, source, target, expected_status
):
    result = registry.resolve(function, source, target)
    assert result["status"] == expected_status
    assert result["equivalent"] is False


def test_exact_known_equivalent_function_is_reported_equivalent(registry):
    result = registry.resolve("ROW_NUMBER", "postgres", "mysql")
    assert result["status"] == "equivalent"
    assert result["equivalent"] is True


def test_unknown_function_is_unknown(registry):
    result = registry.resolve("DOES_NOT_EXIST", "postgres", "mysql")
    assert result["status"] == "unknown"
    assert result["equivalent"] is False
    assert result["function"] == "DOES_NOT_EXIST"
