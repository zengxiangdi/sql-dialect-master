import pytest

from backend.core.exceptions import ErrorCode
from backend.core.transpiler import SQLTranspiler


@pytest.fixture
def transpiler() -> SQLTranspiler:
    return SQLTranspiler()


@pytest.mark.parametrize(
    ("sql", "source", "target", "message"),
    [
        (123, "mysql", "postgres", "sql must be a string"),
        ("SELECT 1", 123, "postgres", "source must be a string"),
        ("SELECT 1", "mysql", 123, "target must be a string"),
    ],
)
def test_transpile_rejects_non_string_inputs(transpiler, sql, source, target, message):
    result = transpiler.transpile(sql, source, target)

    assert result.success is False
    assert result.error_code == ErrorCode.VALIDATION_FAILED.value
    assert result.error == message


def test_transpile_rejects_empty_sql_before_dialect_work(transpiler):
    result = transpiler.transpile("   ", "mysql", "postgres")

    assert result.success is False
    assert result.error_code == ErrorCode.VALIDATION_FAILED.value
    assert result.error == "Empty SQL statement"


def test_transpile_rejects_multiple_statements_with_stable_validation_code(transpiler):
    result = transpiler.transpile("SELECT 1; SELECT 2", "mysql", "postgres")

    assert result.success is False
    assert result.error_code == ErrorCode.VALIDATION_FAILED.value
    assert result.error == (
        "Multiple SQL statements are not supported; submit one statement per request"
    )
