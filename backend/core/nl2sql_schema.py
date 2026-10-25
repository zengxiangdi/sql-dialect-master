"""Schema context and SQL reference validation shared by NL2SQL paths.

The API owns request validation, while this module owns the dependency-free
core representation and the SQLGlot scope checks used by both deterministic
and LLM generation.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import cast

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


class SchemaValidationError(ValueError):
    """Raised when generated SQL cannot be grounded in a schema."""


def _identifier_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise SchemaValidationError("invalid schema identifier")
    parts = tuple(value.split("."))
    if not parts or any(not _IDENTIFIER.fullmatch(part) for part in parts):
        raise SchemaValidationError("invalid schema identifier")
    return parts


def _key(value: str) -> str:
    return value.casefold()


@dataclass(frozen=True)
class SchemaTableContext:
    """Canonical table metadata; empty columns mean metadata is absent."""

    name: str
    columns: frozenset[str]
    has_column_metadata: bool

    @property
    def key(self) -> str:
        return _key(self.name)


@dataclass(frozen=True)
class SchemaRelationshipContext:
    """One explicitly declared relationship between two schema tables."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str

    @property
    def pair(self) -> tuple[str, str]:
        return _key(self.from_table), _key(self.to_table)


@dataclass(frozen=True)
class SchemaContext:
    """Immutable schema indexes shared by deterministic and LLM generation."""

    tables: tuple[SchemaTableContext, ...] = ()
    relationships: tuple[SchemaRelationshipContext, ...] = ()
    _valid: bool = field(default=True, repr=False, compare=False)
    _tables_by_key: dict[str, SchemaTableContext] = field(
        default_factory=dict, repr=False, compare=False
    )
    _tables_by_basename: dict[str, tuple[SchemaTableContext, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _column_owners: dict[str, tuple[SchemaTableContext, ...]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _relationships_by_pair: dict[
        tuple[str, str], tuple[SchemaRelationshipContext, ...]
    ] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None) -> "SchemaContext":
        """Build a normalized context without importing API/Pydantic models."""
        if mapping is None:
            return cls()
        if not isinstance(mapping, Mapping):
            return cls(_valid=False)

        valid = True
        raw_tables = mapping.get("tables", [])
        raw_relationships = mapping.get("relationships", [])
        if not isinstance(raw_tables, (list, tuple)) or not isinstance(
            raw_relationships, (list, tuple)
        ):
            return cls(_valid=False)

        tables: list[SchemaTableContext] = []
        tables_by_key: dict[str, SchemaTableContext] = {}
        basename_candidates: dict[str, list[SchemaTableContext]] = {}
        column_candidates: dict[str, list[SchemaTableContext]] = {}
        for raw_table in raw_tables:
            if not isinstance(raw_table, Mapping):
                valid = False
                continue
            try:
                table_parts = _identifier_parts(raw_table.get("name"))
            except SchemaValidationError:
                valid = False
                continue
            canonical_name = ".".join(table_parts)
            raw_columns = raw_table.get("columns", [])
            if not isinstance(raw_columns, (list, tuple)):
                valid = False
                continue
            columns: set[str] = set()
            has_metadata = bool(raw_columns)
            for raw_column in raw_columns:
                if not isinstance(raw_column, Mapping):
                    valid = False
                    continue
                try:
                    column_name = ".".join(_identifier_parts(raw_column.get("name")))
                except SchemaValidationError:
                    valid = False
                    continue
                columns.add(column_name)
            table = SchemaTableContext(
                name=canonical_name,
                columns=frozenset(columns),
                has_column_metadata=has_metadata,
            )
            if table.key in tables_by_key:
                valid = False
            else:
                tables_by_key[table.key] = table
            tables.append(table)
            basename = _key(table_parts[-1])
            basename_candidates.setdefault(basename, []).append(table)
            for column in columns:
                column_candidates.setdefault(_key(column), []).append(table)

        relationships: list[SchemaRelationshipContext] = []
        relationships_by_pair: dict[
            tuple[str, str], list[SchemaRelationshipContext]
        ] = {}
        for raw_relationship in raw_relationships:
            if not isinstance(raw_relationship, Mapping):
                valid = False
                continue
            try:
                from_table = ".".join(_identifier_parts(raw_relationship.get("from_table")))
                from_column = ".".join(_identifier_parts(raw_relationship.get("from_column")))
                to_table = ".".join(_identifier_parts(raw_relationship.get("to_table")))
                to_column = ".".join(_identifier_parts(raw_relationship.get("to_column")))
            except SchemaValidationError:
                valid = False
                continue
            relationship = SchemaRelationshipContext(
                from_table=from_table,
                from_column=from_column,
                to_table=to_table,
                to_column=to_column,
            )
            from_context = tables_by_key.get(_key(from_table))
            to_context = tables_by_key.get(_key(to_table))
            if from_context is None or to_context is None:
                valid = False
            if from_context and from_context.has_column_metadata and _key(from_column) not in {
                _key(column) for column in from_context.columns
            }:
                valid = False
            if to_context and to_context.has_column_metadata and _key(to_column) not in {
                _key(column) for column in to_context.columns
            }:
                valid = False
            relationships.append(relationship)
            relationships_by_pair.setdefault(relationship.pair, []).append(relationship)
            reverse = SchemaRelationshipContext(
                from_table=to_table,
                from_column=to_column,
                to_table=from_table,
                to_column=from_column,
            )
            relationships_by_pair.setdefault(reverse.pair, []).append(reverse)

        return cls(
            tables=tuple(tables),
            relationships=tuple(relationships),
            _valid=valid,
            _tables_by_key=tables_by_key,
            _tables_by_basename={
                name: tuple(candidates)
                for name, candidates in basename_candidates.items()
            },
            _column_owners={
                name: tuple(candidates)
                for name, candidates in column_candidates.items()
            },
            _relationships_by_pair={
                pair: tuple(candidates)
                for pair, candidates in relationships_by_pair.items()
            },
        )

    @property
    def is_valid(self) -> bool:
        return self._valid

    def table_candidates(self, name: str) -> tuple[SchemaTableContext, ...]:
        """Return exact qualified or unique-basename candidates."""
        exact = self._tables_by_key.get(_key(name))
        if exact is not None:
            return (exact,)
        return self._tables_by_basename.get(_key(name), ())

    def column_owners(self, name: str) -> tuple[SchemaTableContext, ...]:
        return self._column_owners.get(_key(name), ())

    def canonical_column(
        self, table: SchemaTableContext, name: str
    ) -> str | None:
        """Return the schema spelling of a column, or ``None`` if unknown."""
        wanted = _key(name)
        for column in table.columns:
            if _key(column) == wanted:
                return column
        return None

    def relationship_candidates(
        self, from_table: str, to_table: str
    ) -> tuple[SchemaRelationshipContext, ...]:
        return self._relationships_by_pair.get(
            (_key(from_table), _key(to_table)), ()
        )


def _schema_reference_name(parts: Sequence[exp.Expr]) -> str:
    """Normalize SQLGlot identifier parts without accepting arbitrary text."""
    if not parts or any(
        not isinstance(part, exp.Identifier)
        or not _IDENTIFIER.fullmatch(part.name)
        for part in parts
    ):
        raise SchemaValidationError("invalid SQL schema reference")
    return ".".join(part.name for part in parts).casefold()


def validate_schema_references(
    statement: exp.Expression,
    schema: SchemaContext | Mapping[str, object],
    *,
    reject_ambiguous_unqualified: bool = False,
    scope_traverser=traverse_scope,
) -> None:
    """Validate tables, aliases, scopes, and columns against ``schema``."""
    context = (
        schema
        if isinstance(schema, SchemaContext)
        else SchemaContext.from_mapping(schema)
    )
    if not context.is_valid:
        raise SchemaValidationError("invalid schema")

    table_columns = {
        table.key: {_key(column) for column in table.columns}
        for table in context.tables
    }
    all_columns = set().union(*table_columns.values()) if table_columns else set()
    scopes = scope_traverser(statement)
    sources_by_scope: dict[int, dict[str, exp.Table | Scope]] = {}
    for scope in scopes:
        sources: dict[str, exp.Table | Scope] = {}
        for name, (_, source) in scope.selected_sources.items():
            alias = name.casefold()
            if alias in sources:
                raise SchemaValidationError("ambiguous SQL source alias")
            sources[alias] = source
            if isinstance(source, exp.Table):
                table_name = _schema_reference_name(source.parts)
                if table_name not in table_columns:
                    raise SchemaValidationError("unknown SQL table")
                if not source.alias:
                    sources[table_name] = source
        # SEMI/ANTI join sources may be absent from selected_sources.
        for table in scope.tables:
            table_source = scope.sources.get(table.alias_or_name)
            if isinstance(table_source, exp.Table):
                table_name = _schema_reference_name(table_source.parts)
                if table_name not in table_columns:
                    raise SchemaValidationError("unknown SQL table")
                sources.setdefault(table.alias_or_name.casefold(), table_source)
        sources_by_scope[id(scope)] = sources

    def resolve_source(scope: Scope, qualifier: str) -> exp.Table | Scope:
        current: Scope | None = scope
        while current is not None:
            source = sources_by_scope.get(id(current), {}).get(qualifier)
            if source is not None:
                return source
            if not current.can_be_correlated:
                break
            current = current.parent
        raise SchemaValidationError("unknown SQL table alias")

    output_cache: dict[int, set[str] | None] = {}

    def source_columns(
        source: exp.Table | Scope, visiting: frozenset[int] = frozenset()
    ) -> set[str] | None:
        if isinstance(source, exp.Table):
            name = _schema_reference_name(source.parts)
            columns = table_columns[name]
            return columns or None
        scope_id = id(source)
        if scope_id in output_cache:
            return output_cache[scope_id]
        if scope_id in visiting:
            raise SchemaValidationError("recursive SQL scope")
        visiting = visiting | {scope_id}
        if source.outer_columns:
            columns: set[str] | None = {
                name.casefold() for name in source.outer_columns
            }
        elif source.union_scopes:
            columns = source_columns(source.union_scopes[0], visiting)
        else:
            columns = set()
            for projection in cast(exp.Query, source.expression).selects:
                if not projection.is_star:
                    if projection.alias_or_name:
                        columns.add(projection.alias_or_name.casefold())
                    continue
                projected_sources: Iterable[exp.Table | Scope]
                if isinstance(projection, exp.Column):
                    qualifier = _schema_reference_name(projection.parts[:-1])
                    projected_sources = [resolve_source(source, qualifier)]
                else:
                    projected_sources = sources_by_scope[id(source)].values()
                for projected in projected_sources:
                    projected_columns = source_columns(projected, visiting)
                    if projected_columns is None:
                        output_cache[scope_id] = None
                        return None
                    columns.update(projected_columns)
        output_cache[scope_id] = columns
        return columns

    for scope in scopes:
        for column in scope.find_all(exp.Column):
            if column.table:
                qualifier = _schema_reference_name(column.parts[:-1])
                source = resolve_source(scope, qualifier)
                columns = source_columns(source)
                if (
                    not column.is_star
                    and columns is not None
                    and column.name.casefold() not in columns
                ):
                    raise SchemaValidationError("unknown SQL column")
            elif all_columns and column.name.casefold() not in all_columns:
                raise SchemaValidationError("unknown SQL column")
            elif (
                reject_ambiguous_unqualified
                and len(context.column_owners(column.name)) > 1
            ):
                raise SchemaValidationError("ambiguous SQL column")

