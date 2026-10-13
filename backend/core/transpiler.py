#!/usr/bin/env python3
"""SQL Transpiler - Convert SQL between different database dialects."""
import asyncio
import copy
import hashlib
import json
import logging
import re
import threading
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
from .function_call_scanner import replace_function_calls
from .p1_sql_scanner import (
    mask_non_executable,
    prepare_sql_for_parser,
    split_top_level_args,
)
from .post_processor import PostProcessor
from .rules import DYNAMIC_SEPARATOR_FAIL_NOTE

logger = logging.getLogger(__name__)
_DANGEROUS_OPERATION_PATTERN = re.compile(
    r"\b(DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.IGNORECASE
)
_DANGEROUS_OPERATION_TYPES = (
    exp.Drop,
    exp.TruncateTable,
    exp.Alter,
    exp.Create,
    exp.Grant,
    exp.Revoke,
)
_SYSTEM_CATALOG_NAMES = frozenset(
    {"information_schema", "sys", "sysobjects", "pg_catalog", "all_tables"}
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


def _is_single_statement_stream(statements: list) -> bool:
    """Return true for one statement, including one trailing delimiter comment."""
    if len(statements) == 1 and statements[0] is not None:
        return True
    return (
        len(statements) == 2
        and statements[0] is not None
        and isinstance(statements[1], exp.Semicolon)
    )


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


# Conversion-claim evidence for the static compatibility-notes table.
# Each entry maps a distinctive note substring to the evidence the
# claim needs before it is emitted:
#   source_constructs  — must appear in the user's ORIGINAL SQL
#   target_constructs  — must appear in the FINAL SQL; an empty tuple
#                        marks a source-construct advisory (no
#                        conversion claimed, source evidence only)
#
# Classification rule (B2-3a): a static note is a conversion-result
# claim (Class B, evidence-gated) when its copy explicitly states the
# conversion happened — "… transformation" or "… converted to …" — or
# when a prior audit batch (B2-3) explicitly gated that family
# (LISTAGG/ARRAY_JOIN, CONNECT BY, LATERAL VIEW).  Bare "X → Y" notes
# without completion wording describe a generic source→target mapping
# (dialect-pair information) and remain Class A advisories; that choice
# is deliberate and documented here, and is locked in by
# TestB23A_T1_StaticClaimClassificationComplete — any NEW note with
# completion wording that is not listed below fails that test.
#
# Marker order matters for nested substrings: put the more specific
# marker first ("converted to JSON/VARRAY" before "converted to JSON").
_CONVERSION_NOTE_EVIDENCE = (
    ("LISTAGG → ARRAY_JOIN", ("LISTAGG",), ("ARRAY_JOIN",)),
    ("ARRAY_AGG → LISTAGG", ("ARRAY_AGG",), ("LISTAGG",)),
    ("CONNECT BY → WITH RECURSIVE", ("CONNECT BY",), ("WITH RECURSIVE",)),
    ("LATERAL VIEW EXPLODE → JSON_TABLE", ("LATERAL VIEW",), ("JSON_TABLE",)),
    ("LATERAL VIEW EXPLODE → UNNEST", ("LATERAL VIEW",), ("UNNEST",)),
    ("LATERAL VIEW EXPLODE → LATERAL FLATTEN", ("LATERAL VIEW",), ("FLATTEN",)),
    ("UNNEST → LATERAL VIEW EXPLODE", ("UNNEST",), ("LATERAL VIEW",)),
    ("FLATTEN → LATERAL VIEW EXPLODE", ("FLATTEN",), ("LATERAL VIEW",)),
    ("CROSS/OUTER APPLY → LATERAL VIEW", ("APPLY",), ("LATERAL VIEW",)),
    ("LATERAL VIEW EXPLODE may need manual adjustment", ("LATERAL VIEW",), ()),
    # B2-3a: remaining explicit conversion claims ("transformation" /
    # "converted to" wording) from the static table.
    ("GROUP_CONCAT → STRING_AGG transformation", ("GROUP_CONCAT",), ("STRING_AGG",)),
    ("IFNULL → COALESCE transformation", ("IFNULL",), ("COALESCE",)),
    ("STRING_AGG → GROUP_CONCAT transformation", ("STRING_AGG",), ("GROUP_CONCAT",)),
    ("ARRAY types → JSON transformation", ("ARRAY",), ("JSON",)),
    ("TOP → LIMIT transformation", ("TOP",), ("LIMIT",)),
    ("GETDATE() → NOW() transformation", ("GETDATE",), ("NOW()",)),
    ("Hive ARRAY/MAP types converted to JSON/VARRAY", ("ARRAY", "MAP"), ("JSON", "VARRAY")),
    ("Hive ARRAY/MAP types converted to JSON", ("ARRAY", "MAP"), ("JSON",)),
)


def _executable_upper(sql: str, dialect: str | None = None) -> str:
    """Upper-cased executable-only view of ``sql`` for construct detection.

    Comments, string literals and quoted identifiers are replaced by
    spaces (``mask_non_executable``), so construct evidence is taken
    only from real SQL code: a construct spelled inside a comment, a
    string literal or a quoted identifier is not evidence that the
    source used it or that the final SQL produced it.  Used uniformly
    by both the static-table evidence filter and the dynamic
    conversion-claim checks, so no claim path falls back to raw
    substring matching.
    """
    return mask_non_executable(sql, dialect=dialect).upper()


# Constructs whose evidence requires a FUNCTION-CALL form: the name
# immediately followed by ``(``, with an identifier boundary before it.
# A column named ``STRING_AGG_backup`` therefore never counts as a
# STRING_AGG call.
_FUNCTION_FORM_CONSTRUCTS = frozenset({
    "GROUP_CONCAT", "STRING_AGG", "IFNULL", "COALESCE",
    "LISTAGG", "ARRAY_JOIN", "ARRAY_AGG", "JSON_TABLE",
    "UNNEST", "FLATTEN", "GETDATE", "NOW",
})

# Constructs whose evidence requires TYPE context.  A bare token (a
# column named ``json``) is not evidence of a type conversion; these
# are verified against the parsed AST as DataType nodes (see
# _contains_type_construct).  VARRAY is parsed by sqlglot as a
# USERDEFINED DataType carrying ``kind == "VARRAY"``.
_TYPE_CONSTRUCTS = frozenset({"ARRAY", "MAP", "JSON", "VARRAY"})

# Clause/grammar keywords whose evidence requires SYNTAX context: a
# bare identifier whose text equals one of these is a column, not a
# clause.  Verified against the parsed AST (see
# _contains_clause_construct).
_CLAUSE_AST_CONSTRUCTS = frozenset({
    "LIMIT", "TOP", "MERGE", "PIVOT", "UNPIVOT", "AUTO_INCREMENT",
})

# APPLY is a T-SQL join keyword; grammar evidence requires it to follow
# CROSS or OUTER.  A column named ``apply`` or a reference ``t.apply``
# never matches.
_APPLY_PATTERN = r"(?<![\w$])(?:CROSS|OUTER)\s+APPLY(?![\w$])"

# TOP grammar: TOP only ever appears immediately after
# ``SELECT [ALL | DISTINCT]`` — a position a LIMIT clause never
# occupies.  Used on the executable-masked text together with
# ``exp.Limit`` evidence to distinguish TOP from LIMIT where the AST
# cannot (sqlglot parses both to identical Limit nodes and Snowflake
# supports both keywords).  Each TOP clause contributes exactly one
# match and corresponds to exactly one Limit node, so the counts can be
# compared per SELECT level (see _contains_clause_construct).
_TOP_SELECT_PATTERN = re.compile(
    r"(?<![\w$])SELECT\s+(?:(?:ALL|DISTINCT)\s+)?TOP(?=\s|\()"
)

# Dialects in which sqlglot accepts TOP as a SELECT clause.  Derived
# from actual parse behavior with the installed sqlglot (verified by
# probing every SUPPORTED_DIALECTS entry):
# * parsing ``SELECT TOP 1 * FROM t`` yields a Limit node in exactly
#   oracle, tsql, snowflake and redshift;
# * in each of those dialects a bare column named ``top`` at SELECT
#   position does not parse at all, so counting TOP matches there can
#   never miscount a column;
# * in every other supported dialect ``top`` is an ordinary identifier
#   (e.g. postgres/mysql ``SELECT top FROM t LIMIT 5`` parses with top
#   as a Column) while TOP as a clause does not parse.
# TOP evidence is therefore only counted for dialects in this set —
# dialects without TOP grammar never produce TOP evidence from the
# text position alone.
#
# Oracle is deliberately ABSENT even though its lenient parser accepts
# SELECT TOP: Oracle's official row-limiting syntax is OFFSET/FETCH
# (a Fetch node), not SQL Server-style TOP.  A Limit node in Oracle SQL
# can only come from lenient-parsed invalid TOP, whose identity cannot
# be confirmed — handled by the explicit oracle fail-closed guard in
# _contains_clause_construct instead of by this set.
_TOP_CLAUSE_DIALECTS = frozenset({"tsql", "snowflake", "redshift"})

# SQL identifier character model: Unicode word characters (letters,
# digits, underscore — Python's ``\w``) plus ``$`` (a T-SQL / Databricks
# identifier character).  sqlglot tokenizes ``limit$column`` and
# ``LIMIT列`` as a single identifier, so the boundary classes must
# include both.
_IDENT_START = r"(?<![\w$])"
_IDENT_END = r"(?![\w$])"
# Clause keywords additionally must not be a qualified reference:
# ``t.LIMIT`` / ``t.TOP`` are column references, not LIMIT/TOP clauses.
_IDENT_OR_DOT_START = r"(?<![\w$.])"


def _contains_type_construct(sql: str, dialect: str, construct: str) -> bool:
    """AST evidence that ``sql`` (in ``dialect``) contains the TYPE construct.

    ARRAY/MAP/JSON/VARRAY claims describe type conversions, so a
    standalone token or an ordinary identifier/reference is not
    evidence.  Parse with sqlglot in the given dialect and look for a
    DataType node naming the construct:
    * ARRAY — ``ARRAY<…>`` (Hive family), ``TEXT[]`` (Postgres),
    * MAP — ``MAP<…>``,
    * JSON — ``tags JSON``, ``CAST(x AS JSON)``,
    * VARRAY — a USERDEFINED DataType with ``kind == "VARRAY"``.
    Parse failures yield no evidence (fail closed).
    """
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return False
    for node in tree.walk():
        if not isinstance(node, exp.DataType):
            continue
        if construct == "VARRAY":
            if node.args.get("kind") == "VARRAY":
                return True
        elif getattr(node.this, "name", None) == construct:
            return True
    return False


def _contains_clause_construct(
    sql: str, dialect: str, construct: str, masked_upper: str = ""
) -> bool:
    """AST evidence that ``sql`` (in ``dialect``) contains the clause keyword.

    A bare identifier whose text equals LIMIT/TOP/MERGE/PIVOT/UNPIVOT/
    AUTO_INCREMENT is a column, not a clause; only the parsed AST's
    clause nodes count as evidence:
    * LIMIT and TOP both parse to ``exp.Limit``.  sqlglot provides no
      AST field distinguishing them (verified against the installed
      version: ``SELECT TOP 5`` and ``… LIMIT 5`` both parse to
      Limit(expression=5) with every other arg None), and the dialect
      cannot decide either because Snowflake supports both keywords.
      ``exp.Limit`` therefore counts as "a row-limit construct exists"
      per SELECT level, and the TOP/LIMIT distinction comes from the
      strictly position-constrained TOP grammar on the executable-
      masked text: TOP only ever appears immediately after
      ``SELECT [ALL | DISTINCT]``, a position a LIMIT clause never
      occupies.  Each TOP clause contributes exactly one match and one
      Limit node, so counting associates each construct with its own
      query level — nested queries can carry real TOP and real LIMIT
      evidence at the same time.
    * MERGE parses to ``exp.Merge``;
    * PIVOT / UNPIVOT parse to ``exp.Pivot`` (the ``unpivot`` flag
      distinguishes them);
    * AUTO_INCREMENT parses to ``exp.AutoIncrementColumnConstraint``
      (DDL column constraint).
    Parse failures yield no evidence (fail closed).
    """
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return False
    if construct in ("LIMIT", "TOP"):
        limit_nodes = list(tree.find_all(exp.Limit))
        if not limit_nodes:
            return False
        # A bare column named limit/top yields no Limit node at all
        # (it parses as a Column), and unparseable SQL already failed
        # closed above.  Each SELECT level that has a row-limit
        # construct contributes exactly one Limit node, and each TOP
        # clause contributes exactly one position-constrained match in
        # the masked text (verified: nested queries yield one Limit
        # node per SELECT; a same-level TOP+LIMIT combination does not
        # parse).  Counting therefore associates TOP and LIMIT
        # evidence with their own query levels instead of classifying
        # the whole statement with one global match:
        # * TOP evidence: at least one SELECT-position TOP exists in a
        #   dialect whose grammar actually accepts TOP (see
        #   _TOP_CLAUSE_DIALECTS — a column named ``top`` in e.g.
        #   postgres/mysql never counts);
        # * LIMIT evidence: at least one Limit node is NOT a TOP.
        if dialect == "oracle":
            # Oracle's official row-limiting is OFFSET/FETCH (a Fetch
            # node, handled above as "no Limit node").  A Limit node in
            # Oracle SQL can only come from sqlglot's lenient parse of
            # the SQL Server-style SELECT TOP, which is not valid
            # Oracle syntax — neither TOP nor LIMIT identity can be
            # confirmed, so fail closed for both instead of letting the
            # fall-through counting reclassify the same input as LIMIT.
            return False
        top_count = (
            len(_TOP_SELECT_PATTERN.findall(masked_upper))
            if dialect in _TOP_CLAUSE_DIALECTS
            else 0
        )
        if construct == "TOP":
            return top_count > 0
        return top_count < len(limit_nodes)
    if construct == "MERGE":
        return tree.find(exp.Merge) is not None
    if construct in ("PIVOT", "UNPIVOT"):
        for node in tree.find_all(exp.Pivot):
            is_unpivot = bool(getattr(node, "unpivot", False))
            if construct == "UNPIVOT" and is_unpivot:
                return True
            if construct == "PIVOT" and not is_unpivot:
                return True
        return False
    if construct == "AUTO_INCREMENT":
        return tree.find(exp.AutoIncrementColumnConstraint) is not None
    return False


def _contains_construct(
    masked_upper: str, sql: str, dialect: str, construct: str
) -> bool:
    """Boundary-aware construct detection on executable-masked text.

    Matching semantics per construct kind (uniform for the static
    evidence table and the dynamic claims):

    * multi-word constructs (e.g. ``WITH RECURSIVE``, ``LATERAL VIEW``,
      ``CONNECT BY``) match as a whole phrase with identifier
      boundaries on both sides;
    * function constructs (``GROUP_CONCAT``, ``STRING_AGG``,
      ``IFNULL``, ``COALESCE``, ``LISTAGG``, ``ARRAY_JOIN``, …) require
      the call form ``NAME(`` so identifiers like
      ``GROUP_CONCAT_backup`` or ``schema$LISTAGG`` never match;
    * type constructs (``ARRAY``, ``MAP``, ``JSON``, ``VARRAY``) are
      verified as DataType nodes in the parsed AST of the given
      dialect, never as standalone tokens;
    * clause keywords (``LIMIT``, ``TOP``, ``MERGE``, ``PIVOT``,
      ``UNPIVOT``, ``AUTO_INCREMENT``) are verified as clause AST nodes
      — a bare column named ``limit`` is not a LIMIT clause;
    * ``APPLY`` requires the grammar form ``CROSS|OUTER APPLY``;
    * any other single-word construct matches as a whole token with
      identifier boundaries and must not be a qualified reference
      (``t.LIMIT`` is not a LIMIT clause).

    ``masked_upper`` must already be the executable-masked, upper-cased
    view produced by ``_executable_upper``; ``sql`` is the original
    (unmasked) SQL, used for AST-based type and clause evidence.
    """
    words = construct.split()
    if len(words) > 1:
        pattern = (
            _IDENT_START + r"\s+".join(re.escape(word) for word in words) + _IDENT_END
        )
        return re.search(pattern, masked_upper) is not None
    name = words[0].rstrip("()")
    if name in _TYPE_CONSTRUCTS:
        return _contains_type_construct(sql, dialect, name)
    if name in _CLAUSE_AST_CONSTRUCTS:
        return _contains_clause_construct(sql, dialect, name, masked_upper)
    if name == "APPLY":
        return re.search(_APPLY_PATTERN, masked_upper) is not None
    if name in _FUNCTION_FORM_CONSTRUCTS or construct.endswith("()"):
        pattern = _IDENT_START + re.escape(name) + r"\s*\("
        return re.search(pattern, masked_upper) is not None
    pattern = _IDENT_OR_DOT_START + re.escape(name) + _IDENT_END
    return re.search(pattern, masked_upper) is not None


class _CallableIdentity:
    """Identity wrapper for callable signature fields.

    Python tuple equality calls element ``==``; a callable class may
    override ``__eq__`` with semantic (non-identity) logic, which would
    let two behaviorally different callables compare equal and reuse a
    stale cache version.  This wrapper forces strict object identity
    (``is``) so two distinct callable objects never compare equal.

    The wrapper also holds a strong reference to the callable: the
    previous signature snapshot keeps the old callable alive for as long
    as the snapshot exists, so its ``id()`` cannot be reused by a later
    callable (identity-reuse guard for the payload serialization).
    """

    __slots__ = ("callable",)

    def __init__(self, fn):
        self.callable = fn

    def __eq__(self, other):
        return (
            isinstance(other, _CallableIdentity)
            and self.callable is other.callable
        )

    def __hash__(self):
        return id(self.callable)


def _rule_signature_value(rule, field: str):
    """Return the cache-signature value for one ``TransformRule`` field.

    ``category`` normalizes to its string value; every other field is
    returned as-is.  Callable fields are wrapped in ``_CallableIdentity``
    so tuple comparison in ``_rule_cache_state`` detects callable-object
    replacement by identity (``is``), never by ``==``.
    """
    if field == "category":
        return rule.category.value
    value = getattr(rule, field)
    if field in _RULE_CALLABLE_FIELDS and value is not None:
        return _CallableIdentity(value)
    return value


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
        self._rule_cache_lock = threading.RLock()

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
            security_result = self._validate_security(sql, source.strip().lower())
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
                # Cache values contain lists (warnings, transformations,
                # compatibility notes).  Never return those shared mutable
                # lists directly: a caller appending a warning must not
                # mutate all future responses for the same SQL.
                return TranspileResult(**copy.deepcopy(cached))

        if multiple_statements is None:
            # Preserve the lightweight statement-count helper's one-argument
            # contract (callers/tests may wrap it); the security-enabled path
            # already performed dialect-aware masking above.
            multiple_statements = self._has_multiple_statements(sql)
            # Generic SQL treats `--name` as a comment; MySQL treats it as
            # subtraction unless whitespace follows the two dashes. Check
            # this dialect-specific case even when generic masking skipped it.
            if source == "mysql" and ";" in sql and "--" in sql:
                multiple_statements = self._has_multiple_statements(sql, dialect=source)
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
            parser_sql = prepare_sql_for_parser(sql, source)
            ast_notes: List[str] = []
            semantic_blockers: List[str] = []
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
            elif source == "mysql":
                ast = sqlglot.parse_one(parser_sql, read="mysql")
                if target == "oracle":
                    ast, now_notes = self._ast_mysql_now_to_sysdate(ast, target)
                    ast_notes.extend(now_notes)
                ast, normalization_notes, blockers = self._ast_mysql_target_normalizations(ast, target)
                ast_notes.extend(normalization_notes)
                semantic_blockers.extend(blockers)
                if ast_notes or blockers:
                    transpiled = ast.sql(dialect=target, pretty=pretty)
                else:
                    # Keep the canonical sqlglot path for ordinary MySQL
                    # conversions. This preserves the public error taxonomy
                    # for callers that replace/monitor sqlglot.transpile,
                    # while custom AST rewrites avoid a second serialization.
                    transpiled = sqlglot.transpile(
                        parser_sql, read=source, write=target, pretty=pretty
                    )[0]
            else:
                transpiled = sqlglot.transpile(parser_sql, read=source, write=target, pretty=pretty)[0]
            final_sql, transformations = self.post_processor.process(transpiled, source, target)
            if ast_notes:
                transformations = ast_notes + transformations
            compat_notes = self._get_compatibility_notes(
                source, target, source_sql=sql, final_sql=final_sql
            )
            if executable_sql is not None:
                warnings = security_warnings + self._generate_warnings_masked(
                    executable_sql, source, target
                )
            else:
                warnings = security_warnings + self._generate_warnings(sql, source, target)

            if target == "oracle" and "JSON_OBJECT(" in final_sql.upper():
                # sqlglot 30.x serializes its generic JSONObject node with
                # PostgreSQL-style ``'key': value`` syntax. Oracle requires
                # ``'key' VALUE value``; the AST normalization above first
                # emits a flat comma-separated call so this scanner can make
                # the dialect-specific rewrite without touching literals or
                # comments.
                def oracle_json_object(args: str, original: str) -> str:
                    parts = split_top_level_args(args)
                    if any(mask_non_executable(part).find(":") >= 0 for part in parts):
                        # A JSONObject that survived the AST pass can still
                        # be serialized as ``'key': value`` by sqlglot.
                        # Split only the first top-level-looking colon; JSON
                        # keys and values in this path are already complete
                        # function arguments, so colons inside quoted text
                        # remain untouched by the scanner's masking.
                        normalized = []
                        for part in parts:
                            masked_part = mask_non_executable(part)
                            colon_index = masked_part.find(":")
                            if colon_index < 0:
                                return original
                            normalized.append(
                                f"{part[:colon_index].strip()} VALUE {part[colon_index + 1:].strip()}"
                            )
                        return f"JSON_OBJECT({', '.join(normalized)})"
                    if not parts or len(parts) % 2:
                        return original
                    pairs = [
                        f"{parts[index]} VALUE {parts[index + 1]}"
                        for index in range(0, len(parts), 2)
                    ]
                    return f"JSON_OBJECT({', '.join(pairs)})"

                final_sql = replace_function_calls(
                    final_sql, "JSON_OBJECT", oracle_json_object
                )

            if target == "trino" and "JSON_OBJECT(" in final_sql.upper():
                def trino_json_object(args: str, original: str) -> str:
                    parts = split_top_level_args(args)
                    if any(mask_non_executable(part).find(":") >= 0 for part in parts):
                        pairs = []
                        for part in parts:
                            masked_part = mask_non_executable(part)
                            colon_index = masked_part.find(":")
                            if colon_index < 0:
                                return original
                            pairs.append(
                                f"KEY {part[:colon_index].strip()} VALUE {part[colon_index + 1:].strip()}"
                            )
                        return f"JSON_OBJECT({', '.join(pairs)})"
                    if not parts or len(parts) % 2:
                        return original
                    pairs = [
                        f"KEY {parts[index]} VALUE {parts[index + 1]}"
                        for index in range(0, len(parts), 2)
                    ]
                    return f"JSON_OBJECT({', '.join(pairs)})"

                final_sql = replace_function_calls(
                    final_sql, "JSON_OBJECT", trino_json_object
                )

            if semantic_blockers:
                return TranspileResult(
                    success=False,
                    source_sql=sql,
                    source_dialect=source,
                    target_dialect=target,
                    error="; ".join(semantic_blockers),
                    error_code=ErrorCode.VALIDATION_FAILED.value,
                    compatibility_notes=compat_notes,
                    transformations=transformations,
                    warnings=warnings,
                    target_validation_state="invalid",
                )

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
                self._cache.set(cache_key, copy.deepcopy(result.to_dict()))
            return result
        except Exception as e:
            logger.error(f"Transpile failed: {source} -> {target}, error={str(e)}")
            return TranspileResult(
                success=False, source_sql=sql, source_dialect=source, target_dialect=target,
                error=str(e), error_code=ErrorCode.TRANSPILE_FAILED.value
            )

    @staticmethod
    def _has_multiple_statements(sql: str, dialect: str | None = None) -> bool:
        """Return true when SQL contains more than one parsed statement."""
        if not isinstance(sql, str) or not sql.strip():
            return False
        if ";" not in sql:
            return False
        if ";" not in mask_non_executable(sql, dialect=dialect):
            return False
        try:
            statements = sqlglot.parse(prepare_sql_for_parser(sql, dialect), read=dialect) if dialect else sqlglot.parse(sql)
            return not _is_single_statement_stream(statements) and len(statements) > 1
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
    def _ast_mysql_target_normalizations(
        ast: exp.Expression, target: str
    ) -> tuple[exp.Expression, list[str], list[str]]:
        """Normalize MySQL constructs whose target parser is permissive.

        sqlglot intentionally keeps several MySQL nodes generic when a
        target generator has no exact implementation.  That is useful for
        round-tripping, but returning those strings as ``target_valid`` is
        unsafe: Oracle/T-SQL ``DATE_SUB`` and ClickHouse's three-argument
        spelling are accepted by the parser while failing at execution.
        This pass handles the reviewed, structurally unambiguous forms used
        by the conversion engine and reports JSON aggregate targets that
        have no faithful expression-level equivalent.
        """
        notes: list[str] = []
        blockers: list[str] = []

        def numeric_literal(value: exp.Expression) -> exp.Expression | None:
            if not isinstance(value, exp.Literal):
                return None
            raw = value.this
            if value.is_string and str(raw).isdigit():
                return exp.Literal.number(str(raw))
            if value.is_int:
                return value.copy()
            return None

        def negated(value: exp.Expression) -> exp.Expression:
            return exp.Neg(this=value)

        def date_sub(node: exp.DateSub) -> exp.Expression:
            amount = numeric_literal(node.expression)
            unit = str(node.args.get("unit") or "DAY").upper()
            if amount is None:
                return node
            date_expr = node.this.copy()
            if target in {"oracle", "hive", "spark", "databricks"}:
                if unit in {"MONTH", "YEAR"}:
                    months = amount.copy()
                    if unit == "YEAR":
                        months = exp.Mul(this=months, expression=exp.Literal.number("12"))
                    return exp.Anonymous(
                        this="ADD_MONTHS",
                        expressions=[date_expr, negated(months)],
                    )
                if target in {"hive", "spark", "databricks"} and unit == "DAY":
                    return exp.Anonymous(
                        this="DATE_SUB",
                        expressions=[date_expr, amount.copy()],
                    )
                if target == "oracle":
                    interval = exp.Interval(this=amount.copy(), unit=exp.Var(this=unit))
                    return exp.Sub(this=date_expr, expression=interval)
            if target in {"tsql", "snowflake"}:
                return exp.Anonymous(
                    this="DATEADD",
                    expressions=[exp.Var(this=unit), negated(amount.copy()), date_expr],
                )
            if target == "clickhouse":
                function = {
                    "MONTH": "subtractMonths",
                    "YEAR": "subtractYears",
                    "DAY": "subtractDays",
                    "WEEK": "subtractWeeks",
                }.get(unit)
                if function:
                    return exp.Anonymous(this=function, expressions=[date_expr, amount.copy()])
            if target == "trino":
                return exp.Anonymous(
                    this="DATE_ADD",
                    expressions=[exp.Literal.string(unit), negated(amount.copy()), date_expr],
                )
            return node

        def date_diff(node: exp.DateDiff) -> exp.Expression:
            if target == "oracle":
                return exp.Sub(
                    this=exp.Anonymous(this="TRUNC", expressions=[node.this.copy()]),
                    expression=exp.Anonymous(
                        this="TRUNC", expressions=[node.expression.copy()]
                    ),
                )
            if target == "clickhouse":
                return exp.Anonymous(
                    this="dateDiff",
                    expressions=[
                        exp.Literal.string("day"),
                        node.expression.copy(),
                        node.this.copy(),
                    ],
                )
            if target == "databricks":
                return exp.Anonymous(
                    this="DATEDIFF",
                    expressions=[node.this.copy(), node.expression.copy()],
                )
            return node

        def json_pairs(node: exp.JSONObject) -> list[exp.Expression]:
            pairs: list[exp.Expression] = []
            for key_value in node.expressions:
                if not isinstance(key_value, exp.JSONKeyValue):
                    return []
                pairs.extend([key_value.this.copy(), key_value.expression.copy()])
            return pairs

        def json_aggregate(node: exp.Anonymous) -> exp.Expression:
            if node.this.upper() != "JSON_ARRAYAGG" or not node.expressions:
                return node
            value = node.expressions[0]
            if not isinstance(value, exp.JSONObject):
                return node
            pairs = json_pairs(value)
            if not pairs:
                return node
            if target == "postgres":
                obj = exp.Anonymous(this="JSON_BUILD_OBJECT", expressions=pairs)
                notes.append("Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to JSON_AGG(JSON_BUILD_OBJECT(...))")
                return exp.Anonymous(this="JSON_AGG", expressions=[obj])
            if target == "duckdb":
                obj = exp.Anonymous(this="JSON_OBJECT", expressions=pairs)
                notes.append("Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to JSON_GROUP_ARRAY(JSON_OBJECT(...))")
                return exp.Anonymous(this="JSON_GROUP_ARRAY", expressions=[obj])
            if target == "snowflake":
                obj = exp.Anonymous(this="OBJECT_CONSTRUCT_KEEP_NULL", expressions=pairs)
                notes.append("Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(...))")
                return exp.Anonymous(this="ARRAY_AGG", expressions=[obj])
            if target in {"hive", "spark", "databricks"}:
                obj = exp.Anonymous(this="NAMED_STRUCT", expressions=pairs)
                collect = exp.Anonymous(this="COLLECT_LIST", expressions=[obj])
                notes.append("Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to TO_JSON(COLLECT_LIST(NAMED_STRUCT(...)))")
                return exp.Anonymous(this="TO_JSON", expressions=[collect])
            if target == "trino":
                obj = exp.JSONObject(
                    expressions=[
                        exp.JSONKeyValue(this=pairs[i], expression=pairs[i + 1])
                        for i in range(0, len(pairs), 2)
                    ]
                )
                array = exp.Anonymous(this="ARRAY_AGG", expressions=[obj])
                cast = exp.Cast(this=array, to=exp.DataType.build("JSON"))
                notes.append("Converted JSON_ARRAYAGG(JSON_OBJECT(...)) to JSON_FORMAT(CAST(ARRAY_AGG(JSON_OBJECT(...)) AS JSON))")
                return exp.Anonymous(this="JSON_FORMAT", expressions=[cast])
            if target == "clickhouse":
                # ClickHouse Map values must share one physical type.  A
                # JSON object such as this report mixes integers, strings,
                # decimals, and dates; coercing everything to String would
                # silently change the JSON contract.  Refuse the expression
                # level rewrite instead of returning a query that fails at
                # execution with a map type error.
                blockers.append(
                    "clickhouse cannot preserve mixed-type JSON_ARRAYAGG(JSON_OBJECT(...)) values as a typed map"
                )
                return node
            if target in {"tsql", "redshift"}:
                blockers.append(
                    f"{target} has no portable expression-level equivalent for JSON_ARRAYAGG(JSON_OBJECT(...)); use a target-specific FOR JSON/JSON aggregation rewrite"
                )
            return node

        def transform(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Group) and node.args.get("rollup") and target != "mysql":
                # MySQL stores ``WITH ROLLUP`` as a modifier on GROUP BY.
                # Most other engines use the portable grouping-expression
                # form ``GROUP BY ROLLUP(col)``.  Rebuilding the group node
                # avoids sqlglot's permissive MySQL serialization leaking
                # into a target statement.
                expressions = [value.copy() for value in node.expressions]
                node.set("expressions", [exp.Rollup(expressions=expressions)])
                node.set("rollup", None)
                notes.append(f"Converted MySQL WITH ROLLUP to {target} ROLLUP(...) syntax")
                return node
            if isinstance(node, exp.DateSub):
                replacement = date_sub(node)
                if replacement is not node:
                    notes.append(f"Converted MySQL DATE_SUB interval to {target} date arithmetic")
                return replacement
            if isinstance(node, exp.DateDiff):
                replacement = date_diff(node)
                if replacement is not node:
                    notes.append(f"Converted MySQL DATEDIFF to {target} date arithmetic")
                return replacement
            if isinstance(node, exp.Concat):
                values = [value.copy() for value in node.expressions]
                if target == "tsql":
                    notes.append("Preserved CONCAT for T-SQL to avoid numeric-plus-string coercion")
                    return exp.Anonymous(this="CONCAT", expressions=values)
                if target == "oracle" and len(values) > 2:
                    result = values[0]
                    for value in values[1:]:
                        result = exp.DPipe(this=result, expression=value)
                    notes.append("Converted variadic CONCAT to Oracle concatenation operator")
                    return result
                if target not in {"mysql", "oracle"}:
                    # Several generators serialize CONCAT as ``||``. That
                    # is unsafe when one operand is numeric (for example an
                    # NTILE score) and another is text: PostgreSQL and
                    # DuckDB reject integer || text, while other engines
                    # can coerce it inconsistently. Keep the variadic
                    # function so each target applies its documented string
                    # conversion rules.
                    notes.append(f"Preserved variadic CONCAT for {target} string coercion")
                    return exp.Anonymous(this="CONCAT", expressions=values)
            if target == "snowflake" and isinstance(node, exp.TimeToStr):
                format_value = node.args.get("format")
                if isinstance(format_value, exp.Literal) and format_value.is_string and format_value.this == "%Y-%m-%d":
                    node.set("format", exp.Literal.string("YYYY-MM-DD"))
                    notes.append("Normalized Snowflake date format tokens")
            if isinstance(node, exp.JSONObject):
                pairs = json_pairs(node)
                if pairs and target != "mysql":
                    # Direct JSON_OBJECT calls use the same target-specific
                    # anonymous forms as the aggregate rewrite below.
                    if target == "postgres":
                        notes.append("Converted JSON_OBJECT to JSON_BUILD_OBJECT")
                        return exp.Anonymous(this="JSON_BUILD_OBJECT", expressions=pairs)
                    if target == "duckdb":
                        notes.append("Normalized JSON_OBJECT for DuckDB")
                        return exp.Anonymous(this="JSON_OBJECT", expressions=pairs)
                    if target == "snowflake":
                        notes.append("Converted JSON_OBJECT to OBJECT_CONSTRUCT_KEEP_NULL")
                        return exp.Anonymous(this="OBJECT_CONSTRUCT_KEEP_NULL", expressions=pairs)
                    if target in {"hive", "spark", "databricks"}:
                        notes.append("Converted JSON_OBJECT to NAMED_STRUCT")
                        return exp.Anonymous(this="NAMED_STRUCT", expressions=pairs)
                    if target in {"oracle", "trino"}:
                        notes.append(f"Normalized JSON_OBJECT key/value syntax for {target}")
                        return exp.Anonymous(this="JSON_OBJECT", expressions=pairs)
            if isinstance(node, exp.Anonymous) and node.this.upper() == "JSON_ARRAYAGG":
                return json_aggregate(node)
            return node

        # sqlglot walks replacement parents before their children.  Run the
        # pass twice so scalar expressions nested inside a JSON aggregate
        # (especially Snowflake DATE_FORMAT) are normalized after the outer
        # aggregate/object replacement has been installed.
        ast = ast.transform(transform)
        ast = ast.transform(transform)
        # A nested aggregate is visited once for each replacement pass; avoid
        # duplicating a blocker in the public error contract.
        blockers = list(dict.fromkeys(blockers))
        return ast, notes, blockers

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
            tuple(_rule_signature_value(rule, field_name) for field_name in _RULE_SIGNATURE_FIELDS)
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
            for field_name in _RULE_SIGNATURE_FIELDS:
                value = _rule_signature_value(rule, field_name)
                if field_name in _RULE_CALLABLE_FIELDS:
                    fn = value.callable if isinstance(value, _CallableIdentity) else value
                    value = _callable_cache_identity(fn)
                record[field_name] = value
            records.append(record)
        return json.dumps(records, sort_keys=True)

    def _rule_cache_version(self) -> str:
        """Reuse the rule-version hash until the effective rule state changes."""
        with self._rule_cache_lock:
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

    def _get_compatibility_notes(
        self,
        source: str,
        target: str,
        source_sql: str = "",
        final_sql: str = "",
    ) -> List[str]:
        """Compatibility notes, split by semantic responsibility.

        **Source-construct advisories** (class A) are detected from
        ``source_sql`` — the user's original SQL.  A successfully
        converted final SQL no longer contains the source construct
        (e.g. LIMIT becomes FETCH FIRST), so a final-only check would
        wrongly drop these advisories.

        **Conversion-result claims** (class B) assert a transformation
        actually happened.  They are retained only when the claimed
        target construct appears in ``final_sql`` AND the source
        construct appears in ``source_sql``.  The old code checked the
        original SQL for the target construct (which never appears
        there), dropping real claims for the wrong reason, while
        appending claims for conversions that never happened.
        """
        notes = list(get_compatibility_notes(source, target))
        if not source_sql and not final_sql:
            return notes

        source_upper = _executable_upper(source_sql, source)
        final_upper = _executable_upper(final_sql, target)

        # Class B (static table): notes that claim a conversion happened.
        # Marker identifies the note; the claim survives only with source
        # and final evidence.  An empty target tuple marks an advisory
        # that describes the source construct (source evidence only).
        filtered = []
        for note in notes:
            upper_note = note.upper()
            dropped = False
            for marker, source_constructs, target_constructs in _CONVERSION_NOTE_EVIDENCE:
                if marker.upper() in upper_note:
                    if not any(
                        _contains_construct(source_upper, source_sql, source, c)
                        for c in source_constructs
                    ):
                        dropped = True
                        break
                    # An empty target tuple marks a source-construct
                    # advisory: no final-SQL evidence required.
                    if target_constructs and not any(
                        _contains_construct(final_upper, final_sql, target, c)
                        for c in target_constructs
                    ):
                        dropped = True
                        break
                    break
            if not dropped:
                filtered.append(note)
        notes = filtered

        # Class A: source-construct advisories (generic, not claims of a
        # completed conversion).
        if _contains_construct(source_upper, source_sql, source, "LIMIT") and target == "oracle":
            notes.append("Oracle uses FETCH FIRST n ROWS ONLY (12c+) or ROWNUM for LIMIT")
        if _contains_construct(source_upper, source_sql, source, "AUTO_INCREMENT") and target != "mysql":
            notes.append("AUTO_INCREMENT syntax varies by database")
        if _contains_construct(source_upper, source_sql, source, "MERGE"):
            notes.append("MERGE syntax varies significantly between databases")
        if _contains_construct(source_upper, source_sql, source, "PIVOT") or _contains_construct(source_upper, source_sql, source, "UNPIVOT"):
            notes.append("PIVOT/UNPIVOT syntax varies by database")

        # Class B (dynamic): conversion claims, verified by the final SQL.
        if _contains_construct(source_upper, source_sql, source, "LATERAL VIEW") and target not in ["hive", "spark", "databricks"]:
            if _contains_construct(final_upper, final_sql, target, "UNNEST") or _contains_construct(final_upper, final_sql, target, "JSON_TABLE"):
                notes.append("LATERAL VIEW is Hive/Spark specific, converted to UNNEST/JSON_TABLE")
        if _contains_construct(source_upper, source_sql, source, "CONNECT BY") and target != "oracle":
            if _contains_construct(final_upper, final_sql, target, "WITH RECURSIVE"):
                notes.append("CONNECT BY is Oracle specific, converted to WITH RECURSIVE")
        return notes

    def _generate_warnings(self, sql: str, source: str, target: str) -> List[str]:
        return self._generate_warnings_masked(mask_non_executable(sql, dialect=source), source, target)

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

    def _validate_security(
        self,
        sql: str,
        dialect: str | None = None,
        block_dangerous: bool | None = None,
    ) -> Dict[str, Any]:
        """Validate SQL using the canonical scanner and AST checks.

        ``block_dangerous`` is an optional per-call override used by the
        public validation helper.  Keeping the override local avoids mutating
        the process-wide settings object while preserving the historical
        ``settings.security_block_dangerous`` default for transpilation.
        """
        block = (
            settings.security_block_dangerous
            if block_dangerous is None
            else bool(block_dangerous)
        )
        result = {"blocked": False, "reason": None, "warnings": [], "executable_sql": None}
        executable_sql = mask_non_executable(sql, dialect=dialect)
        result["executable_sql"] = executable_sql
        dangerous_operation = _DANGEROUS_OPERATION_PATTERN.search(executable_sql)
        if dangerous_operation:
            # A keyword can also be a perfectly legal column/alias (for
            # example ``SELECT create FROM audit``).  Parse only when the
            # cheap lexical candidate is present and block only an actual DDL
            # root node.  If parsing fails, retain fail-closed behavior.
            try:
                parsed = sqlglot.parse(sql, read=dialect) if dialect else sqlglot.parse(sql)
                actual_operation = any(
                    isinstance(statement, _DANGEROUS_OPERATION_TYPES)
                    for statement in parsed
                    if statement is not None
                )
            except Exception:
                actual_operation = True
            if actual_operation:
                message = f"Dangerous SQL operation detected: {dangerous_operation.group(1).upper()}"
                if block:
                    result["blocked"] = True
                    result["reason"] = message
                    return result
                result["warnings"].append(f"🔒 Security: {message}")
        if ";" not in sql or ";" not in executable_sql:
            result["multiple_statements"] = False
        else:
            try:
                parsed_statements = sqlglot.parse(prepare_sql_for_parser(sql, dialect), read=dialect) if dialect else sqlglot.parse(sql)
                result["multiple_statements"] = (
                    len(parsed_statements) > 1
                    and not _is_single_statement_stream(parsed_statements)
                )
                if result["multiple_statements"]:
                    message = "Multiple SQL statements detected"
                    if block:
                        result["blocked"] = True
                        result["reason"] = message
                        return result
                    result["warnings"].append(f"🔒 Security: {message}")
            except Exception as exc:
                logger.debug("SQL statement parsing failed during security validation: %s", exc)
        for pattern, message in DANGEROUS_SQL_PATTERNS:
            if pattern.search(executable_sql):
                if message == "System table access detected":
                    # Catalog words in a selected column or alias are not a
                    # catalog access.  Inspect parsed table references and
                    # preserve fail-closed behavior only on parse failure.
                    try:
                        parsed = sqlglot.parse(sql, read=dialect) if dialect else sqlglot.parse(sql)
                        system_table = any(
                            isinstance(table, exp.Table)
                            and (
                                table.name.lower() in _SYSTEM_CATALOG_NAMES
                                or (table.db or "").lower() in _SYSTEM_CATALOG_NAMES
                                or (table.catalog or "").lower() in _SYSTEM_CATALOG_NAMES
                            )
                            for statement in parsed
                            if statement is not None
                            for table in statement.find_all(exp.Table)
                        )
                    except Exception:
                        system_table = True
                    if not system_table:
                        continue
                if block:
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
