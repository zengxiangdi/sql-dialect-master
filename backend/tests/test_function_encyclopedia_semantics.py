import pytest

from backend.core.functions_lookup import FunctionEncyclopedia


@pytest.fixture()
def encyclopedia():
    return FunctionEncyclopedia()


def test_find_equivalent_exposes_strict_semantic_status_without_breaking_legacy_fields(
    encyclopedia,
):
    result = encyclopedia.find_equivalent("CONCAT", "mysql", "postgres")

    assert result["supported_in_target"] is True
    assert result["semantic_status"] == "supported-but-different"
    assert result["semantic_equivalent"] is False


def test_find_equivalent_does_not_infer_semantics_from_syntax_presence(encyclopedia):
    result = encyclopedia.find_equivalent("ROW_NUMBER", "mysql", "postgres")

    assert result["supported_in_target"] is True
    assert result["semantic_status"] == "unknown"
    assert result["semantic_equivalent"] is False


def test_find_equivalent_reports_reviewed_unsupported_pair(encyclopedia):
    result = encyclopedia.find_equivalent("REGEXP_REPLACE", "postgres", "tsql")

    assert result["supported_in_target"] is True
    assert result["semantic_status"] == "unsupported"
    assert result["semantic_equivalent"] is False


def test_resolve_function_semantics_returns_registry_metadata(encyclopedia):
    result = encyclopedia.resolve_function_semantics("LENGTH", "mysql", "oracle")

    assert result["status"] == "supported-but-different"
    assert result["equivalent"] is False
    assert "byte" in result["argument_semantics"]


def test_unknown_function_semantics_remain_explicitly_unknown(encyclopedia):
    result = encyclopedia.resolve_function_semantics("DOES_NOT_EXIST", "mysql", "postgres")

    assert result["status"] == "unknown"
    assert result["equivalent"] is False
    assert result["function"] == "DOES_NOT_EXIST"
