"""Final compatibility hardening patches with quote/comment-aware SQL handling."""

from __future__ import annotations

import re

from sqlglot import exp

from .audit_hardening import _mask_non_executable, _replace_outside
from .config import SUPPORTED_DIALECTS
from .nl2sql import NL2SQLGenerator
from .parser import SQLParser
from .post_processor import PostProcessor


_original_parser_init = SQLParser.__init__


def _parser_init_normalized(self, dialect: str = "hive"):
    return _original_parser_init(self, dialect.strip().lower())


SQLParser.__init__ = _parser_init_normalized


_original_has_aggregation = SQLParser._has_aggregation


def _has_aggregation_complete(self, ast):
    return _original_has_aggregation(self, ast) or ast.find(exp.AggFunc) is not None


SQLParser._has_aggregation = _has_aggregation_complete


_original_decode_to_case = PostProcessor._convert_decode_to_case
_original_process = PostProcessor.process
_original_apply_dialect_adjustments = NL2SQLGenerator._apply_dialect_adjustments
_original_template_generate = NL2SQLGenerator._generate_from_template
_original_generate = NL2SQLGenerator.generate
_SAFE_TABLE_HINT = re.compile(
    r"[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*"
)


def _decode_to_case_with_null_semantics(self, sql: str):
    result, notes = _original_decode_to_case(self, sql)
    result, _ = _replace_outside(
        result,
        re.compile(r"WHEN\s+([^\s]+)\s*=\s*NULL\s+THEN", re.IGNORECASE),
        lambda match: f"WHEN {match.group(1)} IS NULL THEN",
    )
    return result, notes


def _process_with_safe_custom_transforms(self, sql: str, source: str, target: str):
    result, rule_notes = self.engine.apply_rules(sql, source, target)
    result, custom_notes = self._apply_custom_transformations(result, source, target)
    warnings = self._check_warnings(sql, source, target)
    return result, [*rule_notes, *custom_notes, *warnings]


def _apply_dialect_adjustments_safe(self, sql: str, dialect: str):
    if dialect == "oracle":
        result, _ = _replace_outside(
            sql, re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "TRUNC(SYSDATE)"
        )
        result, _ = _replace_outside(
            result,
            re.compile(r"DATE_SUB\(TRUNC\(SYSDATE\),\s*(\d+)\)", re.IGNORECASE),
            lambda m: f"TRUNC(SYSDATE) - {m.group(1)}",
        )
        return result

    if dialect == "tsql":
        result, _ = _replace_outside(
            sql, re.compile(r"\bCURRENT_DATE\b", re.IGNORECASE), "CAST(GETDATE() AS DATE)"
        )
        result, _ = _replace_outside(
            result,
            re.compile(r"DATE_SUB\(CAST\(GETDATE\(\) AS DATE\),\s*(\d+)\)", re.IGNORECASE),
            lambda m: f"DATEADD(DAY, -{m.group(1)}, CAST(GETDATE() AS DATE))",
        )
        return result

    if dialect == "postgres":
        result, _ = _replace_outside(
            sql,
            re.compile(r"DATE_SUB\(CURRENT_DATE,\s*(\d+)\)", re.IGNORECASE),
            lambda m: f"CURRENT_DATE - INTERVAL '{m.group(1)} days'",
        )
        return result

    return _original_apply_dialect_adjustments(self, sql, dialect)


def _generate_from_template_with_order_semantics(
    self, template, match_groups, analysis, dialect, table_hint, column_hints
):
    result = _original_template_generate(
        self, template, match_groups, analysis, dialect, table_hint, column_hints
    )
    if not result.success or template.name != "top_n_query" or not result.sql:
        return result

    request_text = str((match_groups or {}).get("match", "")).lower()
    ascending_requested = bool(
        re.search(r"\b(bottom|lowest|smallest)\b|最低|最少", request_text)
    )
    if ascending_requested:
        result.sql, _ = _replace_outside(
            result.sql,
            re.compile(r"(ORDER BY\s+[^\n]+?)\s+DESC\b", re.IGNORECASE),
            lambda m: f"{m.group(1)} ASC",
        )
        result.explanation = re.sub(
            r"查询前(\d+)条记录", r"查询最低/最少\1条记录", result.explanation
        )
    return result


def _generate_normalized(self, text: str, dialect: str = None, table_hint: str = None, column_hints=None):
    normalized_dialect = (dialect or self.default_dialect).strip().lower()
    if normalized_dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"Unsupported dialect: {dialect}. Supported: {', '.join(SUPPORTED_DIALECTS)}"
        )
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized_table_hint = table_hint.strip() if isinstance(table_hint, str) else table_hint
    if normalized_table_hint and not _SAFE_TABLE_HINT.fullmatch(normalized_table_hint):
        raise ValueError("table_hint must be a simple SQL identifier or dotted identifier")
    if column_hints is not None:
        if not isinstance(column_hints, list) or len(column_hints) > 32:
            raise ValueError("column_hints must be a list containing at most 32 identifiers")
        for index, value in enumerate(column_hints):
            if not isinstance(value, str) or not _SAFE_TABLE_HINT.fullmatch(value.strip()):
                raise ValueError(
                    f"column_hints[{index}] must be a simple SQL identifier or dotted identifier"
                )
        column_hints = [value.strip() for value in column_hints]
    return _original_generate(
        self, text, normalized_dialect, normalized_table_hint, column_hints
    )


# The wrappers below are deliberately scanner-aware. Regexes are only applied to
# executable segments; quoted strings and comments are never transformed.
PostProcessor._convert_decode_to_case = _decode_to_case_with_null_semantics
PostProcessor.process = _process_with_safe_custom_transforms
NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments_safe
NL2SQLGenerator._generate_from_template = _generate_from_template_with_order_semantics
NL2SQLGenerator.generate = _generate_normalized
