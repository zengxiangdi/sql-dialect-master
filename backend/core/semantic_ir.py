"""Semantic intermediate representation for NL2SQL.

The IR deliberately stays independent from SQL syntax and SQL dialects. It
models the meaning of predicates and boolean expressions so later stages can
translate the same structure to SQL ASTs without coupling parsing to string
construction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Literal, Union

ComparisonOperator = Literal["=", "!=", ">", ">=", "<", "<="]
TextOperator = Literal["contains", "not_contains"]
SetOperator = Literal["in", "not_in"]


@dataclass(frozen=True)
class Predicate:
    """Base type for a semantic predicate."""

    field: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly representation of the predicate."""
        return asdict(self)


@dataclass(frozen=True)
class ComparisonPredicate(Predicate):
    """A scalar comparison such as ``age > 18``."""

    operator: ComparisonOperator
    value: Any


@dataclass(frozen=True)
class RangePredicate(Predicate):
    """An inclusive range such as ``price BETWEEN 10 AND 20``."""

    lower: Any
    upper: Any
    inclusive_lower: bool = True
    inclusive_upper: bool = True


@dataclass(frozen=True)
class TextPredicate(Predicate):
    """A semantic text match without committing to LIKE/ILIKE syntax."""

    operator: TextOperator
    value: str


@dataclass(frozen=True)
class NullPredicate(Predicate):
    """A NULL / NOT NULL predicate."""

    is_null: bool = True


@dataclass(frozen=True)
class SetPredicate(Predicate):
    """Membership in or exclusion from a finite set of values."""

    operator: SetOperator
    values: tuple[Any, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("SetPredicate requires at least one value")


@dataclass(frozen=True)
class And:
    """Logical conjunction of two or more expressions."""

    operands: tuple["BooleanExpression", ...]

    def __post_init__(self) -> None:
        if len(self.operands) < 2:
            raise ValueError("And requires at least two operands")

    def to_dict(self) -> Dict[str, Any]:
        """Return a recursively serializable representation."""
        return asdict(self)


@dataclass(frozen=True)
class Or:
    """Logical disjunction of two or more expressions."""

    operands: tuple["BooleanExpression", ...]

    def __post_init__(self) -> None:
        if len(self.operands) < 2:
            raise ValueError("Or requires at least two operands")

    def to_dict(self) -> Dict[str, Any]:
        """Return a recursively serializable representation."""
        return asdict(self)


@dataclass(frozen=True)
class Not:
    """Logical negation of one expression."""

    operand: "BooleanExpression"

    def to_dict(self) -> Dict[str, Any]:
        """Return a recursively serializable representation."""
        return asdict(self)


BooleanExpression = Union[Predicate, And, Or, Not]


@dataclass(frozen=True)
class SemanticQuery:
    """Minimal query-level container for future semantic parsing stages."""

    where: BooleanExpression | None = None
    select_fields: tuple[str, ...] = field(default_factory=tuple)
    table: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a recursively serializable representation."""
        return asdict(self)


__all__ = [
    "And",
    "BooleanExpression",
    "ComparisonPredicate",
    "ComparisonOperator",
    "Not",
    "NullPredicate",
    "Or",
    "Predicate",
    "RangePredicate",
    "SemanticQuery",
    "SetPredicate",
    "SetOperator",
    "TextOperator",
    "TextPredicate",
]
