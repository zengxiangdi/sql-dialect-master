"""B3-1 — TypeMapper mapping-result contract.

``map_type`` used to return ``success=True`` for any known type, even
when the source or target dialect maps to ``"N/A"`` (missing mapping) —
an unsupported conversion looked successful.  The contract now
distinguishes four outcomes via ``mapping_status``:

* ``mapped``             — both dialects have a real mapping
* ``unsupported``        — target dialect has no mapping (``N/A``)
* ``source_unavailable`` — source dialect has no mapping (``N/A``)
* ``unknown_type``       — type absent from the mapping data
* ``unknown_dialect``    — dialect outside SUPPORTED_DIALECTS

``success`` is True only for ``mapped``; ``N/A → N/A`` is never
``mapped``.  These tests use an injected data file with deliberately
partial mappings so the N/A paths are exercised deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.type_mapping import TypeMapper


@pytest.fixture
def partial_data(tmp_path: Path) -> Path:
    """A mapping file where some dialect cells are missing (→ N/A)."""
    data = {
        "mappings": {
            "FULL": {
                "mysql": "INT",
                "postgres": "INTEGER",
                "oracle": "NUMBER",
            },
            "SOURCE_ONLY": {
                "mysql": "INT",
                "postgres": "INTEGER",
                # oracle deliberately missing → N/A on the oracle side
            },
            "TARGET_ONLY": {
                # mysql deliberately missing → N/A on the mysql side
                "postgres": "INTEGER",
                "oracle": "NUMBER",
            },
            "NEITHER": {
                "postgres": "INTEGER",
                # both mysql and oracle deliberately missing
            },
        },
        "precision_warnings": {},
    }
    path = tmp_path / "partial_type_mapping.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def mapper(partial_data: Path) -> TypeMapper:
    return TypeMapper(data_path=partial_data)


class TestB3_1_MappingStatus:
    def test_fully_mapped_is_success(self, mapper):
        result = mapper.map_type("FULL", "mysql", "postgres")
        assert result["success"] is True
        assert result["mapping_status"] == "mapped"
        assert result["source_type"] == "INT"
        assert result["target_type"] == "INTEGER"

    def test_target_unsupported_is_not_success(self, mapper):
        """Target dialect maps to N/A: the conversion is NOT available."""
        result = mapper.map_type("FULL", "mysql", "clickhouse")
        assert result["success"] is False
        assert result["mapping_status"] == "unsupported"
        assert result["target_type"] == "N/A"
        assert "error" in result

    def test_source_unavailable_is_not_success(self, mapper):
        result = mapper.map_type("FULL", "hive", "postgres")
        assert result["success"] is False
        assert result["mapping_status"] == "source_unavailable"
        assert result["source_type"] == "N/A"
        assert "error" in result

    def test_target_only_entry_source_unavailable(self, mapper):
        result = mapper.map_type("TARGET_ONLY", "mysql", "postgres")
        assert result["success"] is False
        assert result["mapping_status"] == "source_unavailable"

    def test_source_only_entry_target_unsupported(self, mapper):
        result = mapper.map_type("SOURCE_ONLY", "mysql", "oracle")
        assert result["success"] is False
        assert result["mapping_status"] == "unsupported"
        assert result["target_type"] == "N/A"

    def test_na_to_na_is_never_mapped(self, mapper):
        """N/A → N/A must not be treated as exact or successful."""
        result = mapper.map_type("NEITHER", "mysql", "oracle")
        assert result["success"] is False
        assert result["mapping_status"] == "source_unavailable"
        assert result["source_type"] == "N/A"
        assert result["target_type"] == "N/A"
        # The returned values are the raw N/A markers, not fabricated
        # equivalents.
        assert result["mapping_status"] != "mapped"

    def test_unknown_type_status(self, mapper):
        result = mapper.map_type("NOSUCHTYPE", "mysql", "postgres")
        assert result["success"] is False
        assert result["mapping_status"] == "unknown_type"
        assert "not found" in result["error"]

    def test_unknown_dialect_status(self, mapper):
        result = mapper.map_type("FULL", "mysql", "made_up_db")
        assert result["success"] is False
        assert result["mapping_status"] == "unknown_dialect"
        assert "made_up_db" in result["error"]


class TestB3_1_BundledMatrixMappedStatus:
    def test_bundled_matrix_known_type_is_mapped(self):
        """The bundled data is complete, so a real pair reports mapped."""
        mapper = TypeMapper()
        result = mapper.map_type("VARCHAR", "mysql", "postgres")
        assert result["success"] is True
        assert result["mapping_status"] == "mapped"
        assert result["target_type"] == "VARCHAR(n)"

    def test_suggest_type_propagates_status(self):
        mapper = TypeMapper()
        result = mapper.suggest_type("VARCHAR", "mysql", "postgres")
        assert result["success"] is True
        assert result["mapping_status"] == "mapped"
        assert isinstance(result["suggestions"], list)
