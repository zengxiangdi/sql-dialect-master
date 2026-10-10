#!/usr/bin/env python3
"""SQL Transpiler - Convert SQL between different database dialects."""
import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import sqlglot
from sqlglot import exp

from .cache import TTLCache
from .config import (
    DANGEROUS_SQL_PATTERNS,
    SUPPORTED_DIALECTS,
    WARNING_SQL_PATTERNS,
    get_compatibility_notes,
    settings,
)
from .exceptions import ErrorCode, ValidationError
from .p1_sql_scanner import mask_non_executable
from .post_processor import PostProcessor
from .rules import DYNAMIC_SEPARATOR_FAIL_NOTE

logger = logging.getLogger(__name__)
_DANGEROUS_OPERATION_PATTERN = re.compile(
    r"\b(DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.IGNORECASE
)


def _contains_sql_keyword(sql: str, keyword: str) -> bool:
    """Return true when a keyword appears as a standalone SQL token."""
    return re.search(rf"\b{re.escape(keyword)}\b", sql, re.IGNORECASE) is not None


def _dml_without_where(sql: str, parsed_statements=None):
    """Return DML operations without WHERE, reusing parsed statements when provided."""
    if parsed_statements is None:
        try:
            parsed_statements = sqlglot.parse(sql)
        except Exception as exc:
            logger.debug("Security AST parse fallback: %s", exc)
            return []
    result = []
    for tree in parsed_statements:
        if tree is None:
            continue
        for node in tree.walk():
            if isinstance(node, exp.Update) and node.args.get("where") is None:
                result.append("UPDATE")
            elif isinstance(node, exp.Delete) and node.args.get("where") is None:
                result.append("DELETE")
    return result


@dataclass
class TranspileResult:
    """Result of SQL transpilation.

    ``target_validation_state`` is one of:

    - ``"target_valid"``  — output parses cleanly under the target dialect
      (or validation was disabled via ``validate=False``).
    - ``"generic_only"``  — target-dialect parser rejected the output but the
      generic SQL parser accepted it.  The conversion is retained with a
      compatibility warning, but the success flag must NOT read as a
      target-validated conversion.
    - ``"invalid"``       — neither the target parser nor the generic parser
      accepts the output; ``success`` is ``False``.
    """
    success: bool
    source_sql: str
    target_sql: Optional[str] = None
    source_dialect: str = ""
    target_dialect: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    compatibility_notes: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    target_validation_state: str = "target_valid"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "source_sql": self.source_sql,
            "target_sql": self.target_sql,
            "source_dialect": self.source_dialect,
            "target_dialect": self.target_dialect,
            "error": self.error,
            "error_code": self.error_code,
            "compatibility_notes": self.compatibility_notes,
            "transformations": self.transformations,
            "warnings": self.warnings,
            "target_validation_state": self.target_validation_state,
        }


# The single field list that determines a rule's effective conversion
# behavior — and therefore the transpiler cache identity.  BOTH
# ``_rule_cache_state`` and ``_build_rule_cache_payload`` derive from
# this list so the two can never drift.  If a new ``TransformRule``
# field changes what a rule does, it must be added here.
_RULE_SIGNATURE_FIELDS = (
    "name",
    "source",
    "target",
    "pattern",
    "replacement",
    "note",
    "category",
    "priority",
    "enabled",
    "function_name",
    "structured_replacement",
    "structured_replacer",
    "full_sql_rewriter",
)

# Signature fields that hold callables; they serialize through
# ``_callable_cache_identity`` in the payload.
_RULE_CALLABLE_FIELDS = ("structured_replacer", "full_sql_rewriter")


def _rule_signature_value(rule, field: str):
    """Return the cache-signature value for one ``TransformRule`` field.

    ``category`` normalizes to its string value; every other field is
    returned as-is.  Callable fields come back as the callable object
    itself, so tuple comparison in ``_rule_cache_state`` detects
    callable-object replacement.
    """
    if field == "category":
        return rule.category.value
    return getattr(rule, field)


def _callable_cache_identity(fn) -> Optional[str]:
    """Process-local payload identity for a callable signature field.

    The transpiler cache is an in-memory, per-instance TTL cache (see
    ``SQLTranspiler.__init__``); it is never persisted across processes.
    Within that scope the callable object's ``id()`` is a stable,
    unique identity for the process lifetime of the rule callables and
    detects callable *replacement*.  The ``module.qualname`` prefix is
    informational only — the operative identity is ``id()``, so two
    distinct callables that happen to share a qualname still produce
    different identities.

    Limitation (deliberate): this identity does NOT detect changes to
    mutable closure state *inside* a callable.  The current rule
    contract's callables are pure module-level functions without
    closure state; if that contract ever allows mutable state, an
    explicit auditable version field must be introduced — object
    identity must not be relied on for that.
    """
    if fn is None:
        return None
    module = getattr(fn, "__module__", "?")
    qualname = getattr(fn, "__qualname__", repr(fn))
    return f"{module}.{qualname}#id:{id(fn)}"


class SQLTranspiler:
    """SQL Transpiler using sqlglot with post-processing for edge cases."""

    def __init__(self):
        self.post_processor = PostProcessor()
        self._cache_enabled = settings.cache_enabled
        self._cache = TTLCache(max_size=settings.cache_max_size, ttl=settings.cache_ttl)
        self._security_enabled = settings.security_check_enabled
        self._rule_cache_snapshot_signature = None
        self._rule_cache_snapshot_version = None

    def transpile(
        self,
        sql: str,
        source: str,
        target: str,
        pretty: bool = True,
        validate: bool = True,
    ) -> TranspileResult:
        if not isinstance(sql, str):
            return TranspileResult(
                success=False,
                source_sql=str(sql),
                source_dialect=source if isinstance(source, str) else str(source),
                target_dialect=target if isinstance(target, str) else str(target),
                error="sql must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if not isinstance(source, str):
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=str(source),
                target_dialect=target if isinstance(target, str) else str(target),
                error="source must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )
        if not isinstance(target, str):
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=str(target),
                error="target must be a string",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        if len(sql) > settings.transpiler_max_sql_length:
            return TranspileResult(
                success=False,
                source_sql=sql[:100] + "...",
                source_dialect=source.strip().lower(),
                target_dialect=target.strip().lower(),
                error=f"SQL exceeds maximum length of {settings.transpiler_max_sql_length} characters",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        source = source.strip().lower()
        target = target.strip().lower()

        logger.info(f"Transpiling SQL: {source} -> {target}, length={len(sql)}")
        logger.debug(f"Input SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}")

        security_warnings: List[str] = []
        multiple_statements: Optional[bool] = None
        executable_sql: Optional[str] = None
        security_enabled = settings.security_check_enabled
        self._security_enabled = security_enabled
        if security_enabled:
            security_result = self._validate_security(sql)
            security_warnings = list(security_result["warnings"])
            multiple_statements = security_result.get("multiple_statements")
            executable_sql = security_result.get("executable_sql")
            if security_result["blocked"]:
                logger.warning(f"SQL blocked by security check: {security_result['reason']}")
                return TranspileResult(
                    success=False,
                    source_sql=sql,
                    source_dialect=source,
                    target_dialect=target,
                    error=f"Security check failed: {security_result['reason']}",
                    error_code=ErrorCode.SECURITY_VIOLATION.value,
                    warnings=security_warnings
                )

        if source not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=f"Unsupported source dialect: {source}. Supported: {', '.join(SUPPORTED_DIALECTS)}",
                error_code=ErrorCode.UNSUPPORTED_DIALECT.value
            )

        if target not in SUPPORTED_DIALECTS:
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=f"Unsupported target dialect: {target}. Supported: {', '.join(SUPPORTED_DIALECTS)}",
                error_code=ErrorCode.UNSUPPORTED_DIALECT.value
            )

        if not sql.strip():
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error="Empty SQL statement", error_code=ErrorCode.VALIDATION_FAILED.value
            )

        if self._cache_enabled:
            cache_key = self._cache_key(sql, source, target, pretty, validate)
            cached = self._cache.get(cache_key)
            if cached:
                logger.info("Returning cached result")
                # Guard against stale cache entries from before the
                # target_validation_state field existed.
                cached.setdefault("target_validation_state", "target_valid")
                return TranspileResult(**cached)

        if multiple_statements is None:
            multiple_statements = self._has_multiple_statements(sql)
        if multiple_statements:
            return TranspileResult(
                success=False,
                source_sql=sql,
                source_dialect=source,
                target_dialect=target,
                error="Multiple SQL statements are not supported; submit one statement per request",
                error_code=ErrorCode.VALIDATION_FAILED.value,
            )

        try:
            ast_notes: List[str] = []
            if source == "clickhouse" and target == "postgres":
                ast = sqlglot.parse_one(sql, read="clickhouse")
                ast, group_notes = self._ast_grouparray_to_arrayagg(ast, target)
                ast_notes.extend(group_notes)
                ast, arrayjoin_notes = self._ast_clickhouse_array_join_to_unnest(ast, target)
                ast_notes.extend(arrayjoin_notes)
                transpiled = ast.sql(dialect="postgres", pretty=pretty)
            elif source == "oracle" and target in ("postgres", "mysql", "hive", "spark"):
                ast = sqlglot.parse_one(sql, read="oracle")
                ast, rownum_notes = self._ast_rownum_to_limit(ast, target)
                ast_notes.extend(rownum_notes)
                transpiled = ast.sql(dialect=target, pretty=pretty)
            elif source == "duckdb" and target in ("hive", "spark"):
                ast = sqlglot.parse_one(sql, read="duckdb")
                ast, list_notes = self._ast_duckdb_list_to_array(ast, target)
                ast_notes.extend(list_notes)
                transpiled = ast.sql(dialect=target, pretty=pretty)
            elif source == "mysql" and target == "oracle":
                ast = sqlglot.parse_one(sql, read="mysql")
                ast, now_notes = self._ast_mysql_now_to_sysdate(ast, target)
                ast_notes.extend(now_notes)
                transpiled = ast.sql(dialect="oracle", pretty=pretty)
            else:
                transpiled = sqlglot.transpile(sql, read=source, write=target, pretty=pretty)[0]
            final_sql, transformations = self.post_processor.process(transpiled, source, target)
            if ast_notes:
                transformations = ast_notes + transformations
            compat_notes = self._get_compatibility_notes(source, target, sql)
            if executable_sql is not None:
                warnings = security_warnings + self._generate_warnings_masked(
                    executable_sql, source, target
                )
            else:
                warnings = security_warnings + self._generate_warnings(sql, source, target)

            target_validation_state = "target_valid"

            # B2-1d: when the dynamic-separator fail-closed path fires,
            # strip the static "STRING_AGG → GROUP_CONCAT transformation"
            # compatibility note so a failed result does not carry a
            # note claiming the conversion succeeded.
            def _strip_contradictory_agg_notes(notes: list) -> list:
                return [
                    n for n in notes
                    if not (
                        "STRING_AGG" in n and "GROUP_CONCAT" in n
                        and n != DYNAMIC_SEPARATOR_FAIL_NOTE
                    )
                ]

            if DYNAMIC_SEPARATOR_FAIL_NOTE in transformations:
                # B2-1b fail-closed: the structured rewriter left an
                # unconvertible dynamic GROUP_CONCAT SEPARATOR in place
                # and recorded the fail-closed note.  Refuse to report
                # success: the target SQL contains a source-dialect
                # STRING_AGG call that MySQL cannot execute.
                return TranspileResult(
                    success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                    error=DYNAMIC_SEPARATOR_FAIL_NOTE,
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                    compatibility_notes=_strip_contradictory_agg_notes(compat_notes),
                    transformations=transformations,
                    warnings=warnings, target_validation_state="invalid",
                )
            # B2-1b structural guard: even when sqlglot transpiled a
            # STRING_AGG whose dynamic separator it emitted natively
            # (e.g. `SEPARATOR CONCAT(',', UPPER(x))`), MySQL's actual
            # GROUP_CONCAT grammar accepts only a string literal in the
            # SEPARATOR slot.  sqlglot's MySQL dialect is more permissive
            # than real MySQL here, so a parse-OK result is not
            # execution evidence — detect the non-Literal separator and
            # fail closed.
            if target == "mysql" and self._group_concat_dynamic_separator(final_sql):
                guard_note = (
                    "B2-1b fail-closed: GROUP_CONCAT SEPARATOR must be a "
                    "string literal in MySQL; the dynamic separator produced "
                    "by transpilation cannot be expressed in the target "
                    "and the conversion is not executable on MySQL."
                )
                return TranspileResult(
                    success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                    error=guard_note, error_code=ErrorCode.VALIDATION_FAILED.value,
                    compatibility_notes=_strip_contradictory_agg_notes(compat_notes),
                    transformations=transformations,
                    warnings=warnings, target_validation_state="invalid",
                )
            if validate:
                (
                    validation_error,
                    validation_warning,
                    target_validation_state,
                ) = self._validate_output_detailed(final_sql, target)
                if validation_warning:
                    warnings.append(validation_warning)
                if validation_error:
                    logger.error(f"Output SQL validation failed: {source} -> {target}: {validation_error}")
                    return TranspileResult(
                        success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                        error=validation_error, error_code=ErrorCode.VALIDATION_FAILED.value,
                        compatibility_notes=compat_notes, transformations=transformations, warnings=warnings,
                        target_validation_state="invalid",
                    )

            result = TranspileResult(
                success=True,
                source_sql=sql,
                target_sql=final_sql,
                source_dialect=source,
                target_dialect=target,
                compatibility_notes=compat_notes,
                transformations=transformations,
                warnings=warnings,
                target_validation_state=target_validation_state,
            )

            if self._cache_enabled:
                self._cache.set(cache_key, result.to_dict())
            return result
        except Exception as e:
            logger.error(f"Transpile failed: {source} -> {target}, error={str(e)}")
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=str(e), error_code=ErrorCode.TRANSPILE_FAILED.value
            )

    @staticmethod
    def _has_multiple_statements(sql: str) -> bool:
        """Return true when SQL contains more than one parsed statement."""
        if not isinstance(sql, str) or not sql.strip():
            return False
        if ";" not in sql:
            return False
        if ";" not in mask_non_executable(sql):
            return False
        try:
            return len(sqlglot.parse(sql)) > 1
        except Exception:
            return False

    def _ast_rownum_to_limit(self, ast: exp.Expression, target: str) -> Tuple[exp.Expression, List[str]]:
        """AST-first ROWNUM -> LIMIT migration (G6-A1).

        Operates purely on the parsed AST (no string scanning). Migrates the
        legacy safe ROWNUM -> LIMIT semantics: for a single-SELECT Oracle
        statement with exactly one qualifying ``ROWNUM <= N`` predicate
        (bare integer literal N) as the LHS of a comparison, and no ORDER BY /
        GROUP BY / HAVING / DISTINCT / OR / set operations, remove that
        predicate from WHERE (keeping any AND-companions) and set LIMIT to N.
        Returns ``(ast, notes)`` where ``notes`` is empty unless the
        transformation fired.
        """
        # Only single-SELECT shapes are in scope; set operations are out.
        if not isinstance(ast, exp.Select):
            return ast, []

        # Conservative guards: any of these present means we must skip.
        if ast.args.get("order") or ast.args.get("group") or ast.args.get("having"):
            return ast, []
        if ast.args.get("distinct"):
            return ast, []

        where = ast.args.get("where")
        if where is None:
            return ast, []
        where = where.this

        # OR anywhere in the WHERE subtree is out of scope.
        if any(isinstance(node, exp.Or) for node in where.walk()):
            return ast, []

        # Collect every qualifying predicate: LHS is the ROWNUM column,
        # operator is <=, RHS is a bare integer literal.
        qualifying = []
        for node in where.walk():
            if not isinstance(node, exp.LTE):
                continue
            lhs = node.this
            rhs = node.expression
            if not isinstance(lhs, exp.Column) or lhs.name.upper() != "ROWNUM":
                continue
            if not isinstance(rhs, exp.Literal) or rhs.is_string or rhs.is_int is False:
                continue
            qualifying.append((node, rhs))

        # Exactly one qualifying predicate is required.
        if len(qualifying) != 1:
            return ast, []
        pred, bound = qualifying[0]

        # Detach the predicate from the WHERE tree, keeping AND-companions.
        # ``limit`` returns a new expression; capture the result explicitly.
        self._remove_predicate_from_where(ast, where, pred)
        ast = ast.limit(bound)
        note = f"ROWNUM <= {bound.this} converted to LIMIT {bound.this} (AST)"
        return ast, [note]

    def _ast_grouparray_to_arrayagg(self, ast: exp.Expression, target: str) -> Tuple[exp.Expression, List[str]]:
        """AST-first groupArray → ARRAY_AGG migration (clickhouse → postgres, G6-R2).

        Walks the parsed AST and replaces every ``exp.AnonymousAggFunc`` whose
        function name (case-insensitive) is ``groupArray`` with
        ``exp.ArrayAgg(this=node.expressions[0])``.  ``node.expressions[0]`` is
        passed directly as ``this``:

        - simple argument (``Column``)         → ``ARRAY_AGG(x)``
        - DISTINCT argument (``Distinct``)     → ``ARRAY_AGG(DISTINCT x)``  (preserved)
        - nested expression (``Anonymous``)    → ``ARRAY_AGG(nested_expr)``
        - multiple groupArray calls            → one ArrayAgg per call

        Returns ``(ast, notes)`` where ``notes`` is empty unless at least one
        transformation fired.
        """
        found = False

        def _transform(node):
            nonlocal found
            if isinstance(node, exp.AnonymousAggFunc) and node.this.upper() == "GROUPARRAY":
                found = True
                return exp.ArrayAgg(this=node.expressions[0])
            return node

        ast = ast.transform(_transform)
        if found:
            return ast, ["Converted groupArray to ARRAY_AGG"]
        return ast, []

    def _ast_clickhouse_array_join_to_unnest(self, ast: exp.Expression, target: str) -> tuple[exp.Expression, list[str]]:
        """AST-first ClickHouse ARRAY JOIN → UNNEST migration (clickhouse → postgres, P5).

        ClickHouse's ``ARRAY JOIN`` is a collection-join construct with no
        Postgres equivalent; ``sqlglot.transpile`` passes it through
        verbatim, leaving output that the target dialect cannot execute.
        This transform rewrites every ``exp.Join`` with ``kind == "ARRAY"``
        into a ``CROSS JOIN UNNEST(<collection>) AS <alias>(value)``:

        - bare form (``ARRAY JOIN arr``)         → ``CROSS JOIN UNNEST(arr) AS t(value)``
        - explicit alias (``ARRAY JOIN arr AS x``) → ``CROSS JOIN UNNEST(arr) AS x(value)``
        - qualified column (``o.tags``)          → alias preserved, column kept qualified

        The rewritten ``CROSS JOIN UNNEST(...)`` output is Postgres-valid
        and carries the same per-element expansion semantics.
        """
        found = False

        def _build_unnest_join(join_node: exp.Join) -> exp.Join:
            node = join_node.this
            if isinstance(node, exp.Alias):
                user_alias = node.alias
                col = node.this
            else:
                user_alias = None
                col = node
            alias = (
                exp.TableAlias(
                    this=exp.Identifier(this=user_alias),
                    columns=[exp.Identifier(this="value")],
                )
                if user_alias
                else exp.TableAlias(
                    this=exp.Identifier(this="t"),
                    columns=[exp.Identifier(this="value")],
                )
            )
            return exp.Join(kind="CROSS", this=exp.Unnest(expressions=[col], alias=alias, offset=False))

        def _transform(node):
            nonlocal found
            if isinstance(node, exp.Join) and node.kind == "ARRAY":
                found = True
                return _build_unnest_join(node)
            return node

        ast = ast.transform(_transform)
        if found:
            return ast, ["Converted ARRAY JOIN to CROSS JOIN UNNEST"]
        return ast, []

    def _ast_duckdb_list_to_array(self, ast: exp.Expression, target: str) -> tuple[exp.Expression, list[str]]:
        """AST-first DuckDB LIST datatype → ARRAY migration (duckdb → hive/spark, G6-L).

        Walks the parsed AST and replaces every ``exp.DataType`` whose
        ``node.this`` is ``exp.DataType.Type.LIST`` with
        ``exp.DataType.build("ARRAY", expressions=node.expressions)``.
        Inner type parameters are preserved:

        - ``LIST``                  → ``ARRAY``
        - ``LIST(INT)``             → ``ARRAY<INT>``
        - ``LIST(VARCHAR(10))``     → ``ARRAY<STRING>``   (VARCHAR→STRING mapping is native)
        - ``LIST(INTERVAL)``        → ``ARRAY<INTERVAL>``
        - nested / multiple casts    → each LIST node rewritten independently

        Function forms ``LIST(x)`` / ``LIST(DISTINCT x)`` parse as
        ``exp.ArrayAgg``, not ``exp.DataType``, and are never touched by this
        transform; they remain on the sqlglot-native path.
        """
        found = False

        def _transform(node):
            nonlocal found
            if isinstance(node, exp.DataType) and node.this == exp.DataType.Type.LIST:
                found = True
                inner = node.expressions
                return (
                    exp.DataType.build("ARRAY", expressions=inner)
                    if inner
                    else exp.DataType.build("ARRAY")
                )
            return node

        ast = ast.transform(_transform)
        if found:
            return ast, ["Converted LIST to ARRAY (AST)"]
        return ast, []

    def _ast_mysql_now_to_sysdate(self, ast: exp.Expression, target: str) -> tuple[exp.Expression, list[str]]:
        """AST-first MySQL NOW() → Oracle SYSDATE migration (mysql → oracle, G6-R1).

        Walks the parsed AST and replaces every ``exp.Anonymous`` whose function
        name (case-insensitive) is ``NOW`` and which has **no arguments** with
        ``exp.CurrentTimestamp(sysdate=True, join_mark=False)``.

        ``CurrentTimestamp(sysdate=True)`` is a standard sqlglot expression whose
        Oracle-dialect serialization emits bare ``SYSDATE`` — no serializer hack,
        no custom expression class, no dialect modification.

        - ``NOW()``                 → ``SYSDATE``
        - ``NOW(6)`` (precision)    → **not matched** (``node.expressions`` non-empty)
        - string literal ``'NOW()'`` → **not matched** (literal is not ``exp.Anonymous``)
        - SQL comment ``-- NOW()``   → **not matched** (comment text is not in the AST)

        Returns ``(ast, notes)`` where ``notes`` is empty unless at least one
        transformation fired.
        """
        found = False

        def _transform(node):
            nonlocal found
            if (
                isinstance(node, exp.Anonymous)
                and node.this.upper() == "NOW"
                and not node.expressions
            ):
                found = True
                return exp.CurrentTimestamp(sysdate=True, join_mark=False)
            return node

        ast = ast.transform(_transform)
        if found:
            return ast, ["Converted NOW to SYSDATE (AST)"]
        return ast, []

    @staticmethod
    def _remove_predicate_from_where(
        ast: exp.Expression, where: exp.Expression, pred: exp.Expression
    ) -> None:
        """Remove ``pred`` from the WHERE clause of ``ast``.

        If ``pred`` is the whole WHERE, drop the WHERE entirely. If it is one
        branch of a top-level ``And``, keep the other branch.
        """
        parent = pred.parent
        if parent is not None and isinstance(parent, exp.And):
            companion = parent.expression if parent.this is pred else parent.this
            where.replace(companion)
        else:
            # pred is the entire WHERE expression.
            ast.set("where", None)

    def _rule_cache_state(self):
        """Return a mutation-sensitive structural signature for the current rules.

        Derived from ``_RULE_SIGNATURE_FIELDS`` — the SAME field list
        ``_build_rule_cache_payload`` uses, so the two can never drift.
        Callable fields (``structured_replacer`` /
        ``full_sql_rewriter``) are compared by object identity: replacing
        the callable object changes the signature.
        """
        return tuple(
            tuple(_rule_signature_value(rule, field) for field in _RULE_SIGNATURE_FIELDS)
            for rule in self.post_processor.engine.rules
        )

    def _build_rule_cache_payload(self) -> str:
        """Build the canonical rule payload used by the cache identity.

        Derived from the SAME ``_RULE_SIGNATURE_FIELDS`` list as
        ``_rule_cache_state``.  JSON encoding gives unambiguous field
        boundaries (no delimiter-collision risk).  Callable fields
        serialize through ``_callable_cache_identity`` so the payload
        reflects the same callable replacement the state detects.
        """
        records = []
        for rule in self.post_processor.engine.rules:
            record = {}
            for field in _RULE_SIGNATURE_FIELDS:
                value = _rule_signature_value(rule, field)
                if field in _RULE_CALLABLE_FIELDS:
                    value = _callable_cache_identity(value)
                record[field] = value
            records.append(record)
        return json.dumps(records, sort_keys=True)

    def _rule_cache_version(self) -> str:
        """Reuse the rule-version hash until the effective rule state changes."""
        signature = self._rule_cache_state()
        if signature != self._rule_cache_snapshot_signature:
            payload = self._build_rule_cache_payload()
            self._rule_cache_snapshot_signature = signature
            self._rule_cache_snapshot_version = hashlib.sha256(
                payload.encode("utf-8")
            ).hexdigest()[:16]
        return self._rule_cache_snapshot_version

    def _cache_key(self, sql: str, source: str, target: str, pretty: bool, validate: bool = True,) -> str:
        rule_version = self._rule_cache_version()
        security_version = f"{settings.security_check_enabled}|{settings.security_block_dangerous}"
        return f"v4|{rule_version}|{security_version}|{sql}|{source}|{target}|{pretty}|{validate}"

    def _get_compatibility_notes(self, source: str, target: str, sql: str = "") -> List[str]:
        notes = list(get_compatibility_notes(source, target))
        if not sql:
            return notes

        # Filter out notes for transformations that were NOT actually applied.
        # sqlglot may have handled the conversion natively, or may have left
        # the source construct unchanged. Only emit notes when the target SQL
        # actually contains the expected transformed output.
        sql_upper = sql.upper()
        filtered = []
        for note in notes:
            upper_note = note.upper()
            if "LISTAGG" in upper_note and "ARRAY_JOIN" not in upper_note:
                # Note claims ARRAY_JOIN conversion but we don't see it in output
                continue
            if "ARRAY_JOIN" in upper_note and "ARRAY_JOIN" not in sql_upper:
                continue
            if "CONNECT BY" in upper_note and "WITH RECURSIVE" not in sql_upper:
                continue
            if "LATERAL VIEW" in upper_note and ("UNNEST" not in sql_upper and "JSON_TABLE" not in sql_upper):
                continue
            filtered.append(note)
        notes = filtered

        if "LIMIT" in sql_upper and target == "oracle":
            notes.append("Oracle uses FETCH FIRST n ROWS ONLY (12c+) or ROWNUM for LIMIT")
        if "AUTO_INCREMENT" in sql_upper and target != "mysql":
            notes.append("AUTO_INCREMENT syntax varies by database")
        if "LATERAL VIEW" in sql_upper and target not in ["hive", "spark", "databricks"]:
            notes.append("LATERAL VIEW is Hive/Spark specific, converted to UNNEST/JSON_TABLE")
        if "CONNECT BY" in sql_upper and target != "oracle":
            notes.append("CONNECT BY is Oracle specific, converted to WITH RECURSIVE")
        if "MERGE" in sql_upper:
            notes.append("MERGE syntax varies significantly between databases")
        if "PIVOT" in sql_upper or "UNPIVOT" in sql_upper:
            notes.append("PIVOT/UNPIVOT syntax varies by database")
        return notes

    def _generate_warnings(self, sql: str, source: str, target: str) -> List[str]:
        return self._generate_warnings_masked(mask_non_executable(sql), source, target)

    @staticmethod
    def _generate_warnings_masked(masked_sql: str, source: str, target: str) -> List[str]:
        sql_upper = masked_sql.upper()
        warnings = []
        if "DROP TABLE" in sql_upper or "TRUNCATE" in sql_upper:
            warnings.append("⚠️ Dangerous operation detected: DROP/TRUNCATE")
        # NOTE: DML-without-WHERE warnings are produced exclusively by
        # _validate_security via the AST-based _dml_without_where() check.
        # The regex-based check below would duplicate those warnings.
        if "SELECT *" in sql_upper:
            warnings.append("💡 Consider specifying columns instead of SELECT *")
        if "CROSS JOIN" in sql_upper:
            warnings.append("💡 CROSS JOIN can produce large result sets")
        if sql_upper.count("JOIN") > 5:
            warnings.append("💡 Query has many JOINs - consider query optimization")
        if source == "hive" and target in ["mysql", "postgres", "oracle"]:
            if "DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper:
                warnings.append("⚠️ DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
            if "SORT BY" in sql_upper:
                warnings.append("⚠️ SORT BY is Hive-specific, converted to ORDER BY")
        if source in ["hive", "spark"] and target in ["mysql", "postgres"]:
            if "COLLECT_LIST" in sql_upper or "COLLECT_SET" in sql_upper:
                warnings.append("💡 Array aggregation converted - verify result format")
        return warnings

    def _validate_output(self, sql: str, dialect: str) -> Optional[str]:
        """Validate target SQL, preserving the original error-only interface."""
        error, _, _ = self._validate_output_detailed(sql, dialect)
        return error

    def _group_concat_dynamic_separator(self, sql: str) -> bool:
        """True when any GROUP_CONCAT in ``sql`` has a non-Literal SEPARATOR.

        Real MySQL's ``GROUP_CONCAT(expr [SEPARATOR str_val])`` requires a
        string literal in the SEPARATOR slot; sqlglot's MySQL dialect
        accepts arbitrary expressions there, so a parse-OK result is not
        evidence the output is executable MySQL.  Used only when
        ``target == "mysql"`` as a fail-closed guard.
        """
        try:
            tree = sqlglot.parse_one(sql, read="mysql")
        except Exception:
            # Unparseable output is already caught by _validate_output_detailed.
            return False
        for gc in tree.find_all(exp.GroupConcat):
            sep = gc.args.get("separator")
            if sep is not None and not isinstance(sep, exp.Literal):
                return True
        return False

    def _validate_output_detailed(
        self, sql: str, dialect: str
    ) -> tuple[Optional[str], Optional[str], str]:
        """Validate target SQL with a generic-parser compatibility fallback.

        Returns ``(error, warning, target_validation_state)`` where
        ``target_validation_state`` is one of ``"target_valid"`` (target
        parser accepted the output), ``"generic_only"`` (target parser
        rejected it but the generic parser accepted it — the conversion is
        retained, never presented as target-validated), or ``"invalid"``
        (neither parser accepts the output).
        """
        try:
            sqlglot.parse_one(sql, read=dialect)
            return None, None, "target_valid"
        except Exception as target_error:
            target_message = str(target_error)[:100]
            try:
                sqlglot.parse_one(sql)
            except Exception:
                return (
                    f"⚠️ Output SQL may have syntax issues: {target_message}",
                    None,
                    "invalid",
                )

            warning = (
                "⚠️ Target dialect parser rejected the output, but the generic "
                "SQL parser accepted it; retaining the conversion with a "
                f"compatibility warning. Target parser error: {target_message}"
            )
            logger.warning("Generic parser fallback used for %s output: %s", dialect, target_message)
            return None, warning, "generic_only"

    def _validate_security(self, sql: str) -> Dict[str, Any]:
        result = {"blocked": False, "reason": None, "warnings": [], "executable_sql": None}
        executable_sql = mask_non_executable(sql)
        result["executable_sql"] = executable_sql
        dangerous_operation = _DANGEROUS_OPERATION_PATTERN.search(executable_sql)
        if dangerous_operation:
            message = f"Dangerous SQL operation detected: {dangerous_operation.group(1).upper()}"
            if settings.security_block_dangerous:
                result["blocked"] = True
                result["reason"] = message
                return result
            result["warnings"].append(f"🔒 Security: {message}")
        if ";" not in sql or ";" not in executable_sql:
            result["multiple_statements"] = False
        else:
            try:
                parsed_statements = sqlglot.parse(sql)
                result["multiple_statements"] = len(parsed_statements) > 1
                if result["multiple_statements"]:
                    message = "Multiple SQL statements detected"
                    if settings.security_block_dangerous:
                        result["blocked"] = True
                        result["reason"] = message
                        return result
                    result["warnings"].append(f"🔒 Security: {message}")
            except Exception as exc:
                logger.debug("SQL statement parsing failed during security validation: %s", exc)
        for pattern, message in DANGEROUS_SQL_PATTERNS:
            if pattern.search(executable_sql):
                if settings.security_block_dangerous:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")
        masked_upper = executable_sql.upper()
        needs_dml_ast = bool(re.search(r"\b(?:UPDATE|DELETE)\b", masked_upper))
        dml_parsed = None
        if needs_dml_ast and result.get("multiple_statements") is False:
            try:
                dml_parsed = sqlglot.parse(sql)
            except Exception as exc:
                logger.debug("DML security AST parse unavailable: %s", exc)
                dml_parsed = None
        if dml_parsed is not None:
            dml_without_where = set(_dml_without_where(sql, dml_parsed))
            for op in sorted(dml_without_where):
                result["warnings"].append(f"⚠️ {op} without WHERE clause - may affect all rows")
        for pattern, message in WARNING_SQL_PATTERNS:
            if message in {
                "DELETE without WHERE clause - will affect all rows",
                "UPDATE without WHERE clause - will affect all rows",
            }:
                continue
            if pattern.search(executable_sql):
                result["warnings"].append(f"⚠️ {message}")
        return result

    def batch_transpile(self, statements: List[str], source: str, target: str, pretty: bool = True) -> List[TranspileResult]:
        if not isinstance(statements, list):
            raise ValidationError("statements must be a list", field="statements", value=type(statements).__name__)
        if len(statements) > settings.max_batch_size:
            raise ValidationError(f"Batch contains {len(statements)} statements; maximum is {settings.max_batch_size}", field="statements", value=str(len(statements)))
        return [self.transpile(sql, source, target, pretty) for sql in statements]

    async def batch_transpile_async(self, statements: List[str], source: str, target: str, pretty: bool = True, max_concurrent: int = 10) -> List[TranspileResult]:
        if not isinstance(statements, list):
            raise ValidationError("statements must be a list", field="statements", value=type(statements).__name__)
        if len(statements) > settings.max_batch_size:
            raise ValidationError(f"Batch contains {len(statements)} statements; maximum is {settings.max_batch_size}", field="statements", value=str(len(statements)))
        if isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int) or max_concurrent <= 0:
            raise ValidationError("max_concurrent must be a positive integer", field="max_concurrent", value=str(max_concurrent))
        semaphore = asyncio.Semaphore(max_concurrent)

        async def limited_transpile(sql: str) -> TranspileResult:
            async with semaphore:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: self.transpile(sql, source, target, pretty))

        return await asyncio.gather(*(limited_transpile(sql) for sql in statements))

    def get_supported_dialects(self) -> List[str]:
        return SUPPORTED_DIALECTS.copy()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "supported_dialects": len(SUPPORTED_DIALECTS),
            "dialects": SUPPORTED_DIALECTS,
            "post_processor": self.post_processor.get_stats(),
            "cache": self._cache.get_stats() if self._cache_enabled else {"enabled": False},
            "security": {"enabled": self._security_enabled, "block_dangerous": settings.security_block_dangerous},
            "settings": {"cache_enabled": self._cache_enabled, "max_batch_size": settings.max_batch_size, "max_sql_length": settings.transpiler_max_sql_length}
        }

    def clear_cache(self) -> None:
        if self._cache_enabled:
            self._cache.clear()
            logger.info("Transpile cache cleared")
