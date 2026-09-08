"""Systematic SQL conversion coverage across all supported dialect pairs.

The matrix is intentionally small and deterministic: every source/target pair
must successfully convert a dialect-neutral SELECT and the generated SQL must
be parseable using the target dialect. This is a regression gate for the core
transpilation contract, not a claim of semantic equivalence for every SQL
feature.
"""

import pytest

from backend.core.parser import SQLParser, SUPPORTED_DIALECTS
from backend.core.transpiler import SQLTranspiler


@pytest.fixture(scope="module")
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


DIALECT_PAIRS = [
    (source, target)
    for source in SUPPORTED_DIALECTS
    for target in SUPPORTED_DIALECTS
]


@pytest.mark.parametrize("source,target", DIALECT_PAIRS)
def test_basic_select_converts_and_validates(
    transpiler: SQLTranspiler, source: str, target: str
) -> None:
    """Every supported source/target pair produces valid target SQL."""
    sql = "SELECT id, name FROM users WHERE status = 1"

    result = transpiler.transpile(sql, source, target)

    assert result.success, (
        f"Conversion failed for {source} -> {target}: {result.error}"
    )
    assert result.target_sql

    is_valid, error = SQLParser(target).validate(result.target_sql)
    assert is_valid, f"Invalid target SQL for {source} -> {target}: {error}"


def test_matrix_covers_all_supported_dialects() -> None:
    """The regression suite must remain aligned with the configured dialect list."""
    expected_pairs = len(SUPPORTED_DIALECTS) ** 2
    assert len(DIALECT_PAIRS) == expected_pairs
    assert len({source for source, _ in DIALECT_PAIRS}) == len(SUPPORTED_DIALECTS)
    assert len({target for _, target in DIALECT_PAIRS}) == len(SUPPORTED_DIALECTS)
