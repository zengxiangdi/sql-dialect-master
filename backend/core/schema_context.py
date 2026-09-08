"""Immutable schema metadata used by semantic SQL generation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SchemaColumn:
    """A column exposed by a semantic SQL schema."""

    name: str
    data_type: str | None = None
    alias: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Schema column name cannot be empty")


@dataclass(frozen=True)
class SchemaTable:
    """A table and its known columns."""

    name: str
    columns: tuple[SchemaColumn, ...] = field(default_factory=tuple)
    alias: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Schema table name cannot be empty")


@dataclass(frozen=True)
class SchemaContext:
    """Deterministic table/column resolution context for semantic queries."""

    tables: tuple[SchemaTable, ...] = field(default_factory=tuple)
    default_table: str | None = None

    def resolve_table(self, name: str | None = None) -> SchemaTable:
        """Resolve a table by name/alias, or use the configured default."""
        requested = (name or self.default_table or "").strip()
        if not requested:
            raise ValueError("Schema table is required")

        matches = [
            table
            for table in self.tables
            if table.name == requested or table.alias == requested
        ]
        if not matches:
            raise KeyError(f"Unknown schema table: {requested}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous schema table: {requested}")
        return matches[0]

    def resolve_column(self, name: str, table: str | None = None) -> tuple[SchemaTable, SchemaColumn]:
        """Resolve a column and reject missing or ambiguous references."""
        requested = name.strip() if name else ""
        if not requested:
            raise ValueError("Schema column is required")

        scoped = [self.resolve_table(table)] if table else list(self.tables)
        matches: list[tuple[SchemaTable, SchemaColumn]] = []
        for schema_table in scoped:
            for column in schema_table.columns:
                if column.name == requested or column.alias == requested:
                    matches.append((schema_table, column))

        if not matches:
            raise KeyError(f"Unknown schema column: {requested}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous schema column: {requested}")
        return matches[0]


__all__ = ["SchemaColumn", "SchemaContext", "SchemaTable"]
