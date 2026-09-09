from backend.core.nl2sql import NL2SQLGenerator


def test_column_hints_contract_accepts_supported_shapes():
    generator = NL2SQLGenerator()

    for hints in (
        None,
        [],
        ["id"],
        ["users.id", "users.name"],
        tuple(["users.id"]),
    ):
        result = generator.generate("查询所有用户", "mysql", "users", hints)
        assert result.success is True
        assert result.sql is not None


def test_column_hints_contract_rejects_invalid_shapes():
    generator = NL2SQLGenerator()

    invalid_values = (
        "users.id",
        [""],
        ["   "],
        [1],
        ["users.id()"],
        ["users-id"],
        ["users..id"],
        ["users.id; DROP TABLE users"],
        ["users.id"] * 101,
    )

    for hints in invalid_values:
        result = generator.generate("查询所有用户", "mysql", "users", hints)
        assert result.success is False
        assert result.confidence == 0.0
        assert result.sql is None


def test_column_hints_contract_preserves_dotted_identifiers():
    generator = NL2SQLGenerator()
    result = generator.generate(
        "查询用户",
        "mysql",
        "users",
        ["users.id", "users.name"],
    )

    assert result.success is True
    assert "users.id" in result.sql
    assert "users.name" in result.sql
