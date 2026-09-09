import pytest

from backend.core.type_mapping import TypeMapper


@pytest.fixture()
def mapper():
    return TypeMapper()


def test_unknown_type_does_not_fall_back_to_partial_match(mapper):
    result = mapper.map_type("INTEGERX", "postgres", "mysql")

    assert result["success"] is False
    assert result["target_type"] is None
    assert "INTEGERX" in result["error"]


def test_known_canonical_type_still_maps(mapper):
    result = mapper.map_type("INTEGER", "postgres", "mysql")

    assert result["success"] is True
    assert result["source_type"] == "INTEGER"
    assert result["target_type"] == "INT"
