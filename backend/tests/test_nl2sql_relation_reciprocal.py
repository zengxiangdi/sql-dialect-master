#!/usr/bin/env python3
"""Regression tests: NL2SQL relation correctness.

Locks two invariants:

1. Reciprocal join-key correctness — for every known relationship the
   join key is semantically symmetric: ``guess_join_key(A, B)`` and
   ``guess_join_key(B, A)`` must reference the same two columns, only
   with the sides swapped.  A column-mapping asymmetry (e.g. forward
   says ``A.id = B.a_id`` but backward says ``B.id = A.a_id``) is a
   bug even though both look plausible.
2. Physical JOIN parsing — explicit physical join intent
   (LEFT / RIGHT / INNER / OUTER, English and Chinese) must be parsed
   into a structured ``JoinSpec``.  The legacy
   ``text.split()[0].upper()`` heuristic is removed; join type must
   never be inferred from the first token of the whole sentence.
3. Unknown relationships fail closed — ``guess_join_key`` returns
   None and the join record carries ``condition=None`` so the
   generator must not fabricate a condition.
"""
from __future__ import annotations

import re

import pytest

from backend.core.nl2sql_components.relations import (
    JOIN_KEY_PATTERNS,
    extract_joins,
    guess_join_key,
    parse_join_spec,
)
from backend.core.nl2sql_components.relations import JoinSpec
from backend.core.nl2sql_legacy import NL2SQLGenerator

# Every known relationship, both directions for the reciprocal test.
RECIProCAL_PAIRS = [
    ("users", "orders"),
    ("users", "transactions"),
    ("orders", "products"),
    ("products", "orders"),
    ("employees", "departments"),
    ("departments", "employees"),
    ("customers", "orders"),
    ("orders", "customers"),
    ("orders", "payments"),
]


def _columns_of_condition(condition: str) -> set[tuple[str, str]]:
    """Normalize ``a.b = c.d`` to the set of {lhs, rhs} column tokens."""
    lhs, rhs = condition.split("=", 1)
    return {lhs.strip().lower(), rhs.strip().lower()}


class TestReciprocalJoinKeySymmetry:
    """Forward and backward join keys must map the same columns."""

    @pytest.mark.parametrize(("table_a", "table_b"), RECIProCAL_PAIRS)
    def test_reciprocal_pair_has_both_directions(
        self, table_a: str, table_b: str
    ) -> None:
        assert (table_a, table_b) in JOIN_KEY_PATTERNS, (
            f"missing forward pattern {table_a} -> {table_b}"
        )
        assert (table_b, table_a) in JOIN_KEY_PATTERNS, (
            f"missing reverse pattern {table_b} -> {table_a}"
        )

    @pytest.mark.parametrize(("table_a", "table_b"), RECIProCAL_PAIRS)
    def test_reciprocal_keys_map_same_columns(
        self, table_a: str, table_b: str
    ) -> None:
        from backend.core.nl2sql_components.relations import guess_join_key

        forward = guess_join_key(table_a, table_b)
        backward = guess_join_key(table_b, table_a)
        assert forward is not None, f"no forward key for {table_a} -> {table_b}"
        assert backward is not None, f"no reverse key for {table_b} -> {table_a}"
        assert _columns_of_condition(forward) == _columns_of_condition(backward), (
            f"reciprocal keys disagree on column mapping:\n"
            f"  {table_a} -> {table_b}: {forward}\n"
            f"  {table_b} -> {table_a}: {backward}"
        )

    def test_unknown_relationship_returns_none(self) -> None:
        from backend.core.nl2sql_components.relations import guess_join_key

        assert guess_join_key("invoices", "shipments") is None
        assert guess_join_key("users", "invoices") is None

    def test_unknown_pair_not_fabricated_in_extract(self) -> None:
        """extract_joins must not invent a condition for unknown pairs."""
        tables = {"invoices": "invoices", "shipments": "shipments"}
        joins = extract_joins("join invoices and shipments", tables)
        assert joins, "expected a join record"
        for join in joins:
            assert join["condition"] is None, (
                "unknown relationship must fail closed (condition=None)"
            )


class TestPhysicalJoinSpecParsing:
    """Explicit join-type keywords must parse into a structured spec."""

    @pytest.mark.parametrize(
        ("text", "expected_kind"),
        [
            ("left join users and orders", "LEFT"),
            ("LEFT JOIN users and orders", "LEFT"),
            ("users left join orders", "LEFT"),
            ("right join users and orders", "RIGHT"),
            ("RIGHT JOIN users and orders", "RIGHT"),
            ("inner join users and orders", "INNER"),
            ("outer join users and orders", "OUTER"),
            ("SELECT orders, users LEFT JOIN ON ...", "LEFT"),
        ],
    )
    def test_explicit_join_keywords_parse(self, text: str, expected_kind: str) -> None:
        spec = parse_join_spec(text)
        assert spec is not None, f"expected a join spec in {text!r}"
        assert spec.kind == expected_kind

    def test_no_join_keyword_returns_none(self) -> None:
        assert parse_join_spec("users who have orders") is None
        assert parse_join_spec("SELECT * FROM users") is None

    def test_join_type_never_inferred_from_first_token(self) -> None:
        """The legacy ``text.split()[0].upper()`` bug: a sentence that
        starts with a table name must not have its join type read from
        the first word.

        Regression: 'users left join orders' used to yield join_type
        'USERS' (the first token), which is not a valid SQL join type.
        """
        spec = parse_join_spec("users left join orders")
        assert spec is not None
        # If the first-token heuristic is back, kind would be "USERS".
        assert spec.kind not in ("USERS", "ORDERS"), (
            f"join type inferred from sentence-first token: {spec.kind}"
        )
        assert spec.kind == "LEFT"

    def test_chinese_join_keywords(self) -> None:
        assert parse_join_spec("右连接 用户 和 订单").kind == "RIGHT"
        assert parse_join_spec("内连接 用户 和 订单").kind == "INNER"


class TestExtractJoinsStructured:
    """extract_joins must surface the parsed JoinSpec, not a bare string."""

    def test_join_record_carries_join_spec(self) -> None:
        tables = {"users": "users", "orders": "orders"}
        joins = extract_joins("left join users and orders", tables)
        assert joins
        spec = joins[0].get("join_spec")
        assert spec is not None, "join records must carry the parsed JoinSpec"
        assert spec.kind == "LEFT"

    def test_plain_join_defaults_to_inner(self) -> None:
        tables = {"users": "users", "orders": "orders"}
        joins = extract_joins("join users and orders", tables)
        assert joins
        spec = joins[0]["join_spec"]
        assert spec.kind in ("INNER", "JOIN"), (
            f"unqualified 'join' must default to inner, got {spec.kind}"
        )


class TestNl2SqlEndToEnd:
    """NL2SQL output must render the structured join kind into SQL.

    These lock the full pipeline (natural language -> JoinSpec ->
    physical JOIN / EXISTS clause) so that the first-token regression
    or a bare JOIN reappearing in generated SQL is caught immediately.
    """

    @pytest.mark.parametrize(
        "text, expected_join",
        [
            ("left join users and orders", "LEFT JOIN orders"),
            ("right join users and orders", "RIGHT JOIN orders"),
            ("inner join users and orders", "INNER JOIN orders"),
            ("outer join users and orders", "OUTER JOIN orders"),
        ],
    )
    def test_explicit_join_kind_renders_in_sql(self, text: str, expected_join: str) -> None:
        result = NL2SQLGenerator().generate(text)
        assert result.success, f"generation failed: {result.explanation}"
        assert expected_join in result.sql, (
            f"expected '{expected_join}' in SQL, got: {result.sql}"
        )

    def test_unqualified_join_defaults_to_inner_in_sql(self) -> None:
        result = NL2SQLGenerator().generate("join users and orders")
        assert result.success
        sql_upper = result.sql.upper()
        # Unqualified "JOIN" must render as INNER JOIN or a plain JOIN,
        # never as a garbage token like "USERS JOIN".
        assert "JOIN" in sql_upper
        assert "USERS JOIN" not in sql_upper

    def test_relational_existence_uses_exists_not_join(self) -> None:
        result = NL2SQLGenerator().generate("show users who have orders")
        assert result.success
        sql_upper = result.sql.upper()
        assert "EXISTS" in sql_upper, (
            f"relational existence should use EXISTS, got: {result.sql}"
        )
        assert "LEFT JOIN" not in sql_upper
        assert "RIGHT JOIN" not in sql_upper

    def test_negative_existence_uses_not_exists(self) -> None:
        result = NL2SQLGenerator().generate("show users without orders")
        assert result.success
        sql_upper = result.sql.upper()
        assert "NOT EXISTS" in sql_upper or "NOT" in sql_upper, (
            f"negative relational existence should use NOT EXISTS, got: {result.sql}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
