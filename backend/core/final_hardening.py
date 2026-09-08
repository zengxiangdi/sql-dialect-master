"""Final compatibility hardening patches for legacy helper implementations."""

import re

from sqlglot import exp

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


def _decode_to_case_with_null_semantics(self, sql: str):
    result, notes = _original_decode_to_case(self, sql)
    result = re.sub(
        r"WHEN\s+([^\s]+)\s*=\s*NULL\s+THEN",
        r"WHEN \1 IS NULL THEN",
        result,
        flags=re.IGNORECASE,
    )
    return result, notes


PostProcessor._convert_decode_to_case = _decode_to_case_with_null_semantics


_original_process = PostProcessor.process


def _process_with_group_concat_default_separator(self, sql: str, source: str, target: str):
    result, notes = _original_process(self, sql, source, target)
    if source.lower() == "mysql" and target.lower() == "postgres":
        result = re.sub(
            r"STRING_AGG\(([^()]+)::TEXT,\s*''\)",
            r"STRING_AGG(\1::TEXT, ',')",
            result,
            flags=re.IGNORECASE,
        )
    return result, notes


PostProcessor.process = _process_with_group_concat_default_separator


_original_extract_conditions = NL2SQLGenerator._extract_conditions_enhanced


def _extract_conditions_with_english_inclusive_comparisons(self, text: str, original: str):
    conditions = _original_extract_conditions(self, text, original)

    if re.search(r"\bgreater\s+than\s+or\s+equal\s+to\b", text, re.IGNORECASE):
        conditions = [
            re.sub(r"\s>\s(\d+\.?\d*)$", r" >= \1", condition, count=1)
            for condition in conditions
        ]

    if re.search(r"\bless\s+than\s+or\s+equal\s+to\b", text, re.IGNORECASE):
        conditions = [
            re.sub(r"\s<\s(\d+\.?\d*)$", r" <= \1", condition, count=1)
            for condition in conditions
        ]

    return conditions


NL2SQLGenerator._extract_conditions_enhanced = _extract_conditions_with_english_inclusive_comparisons


_original_apply_dialect_adjustments = NL2SQLGenerator._apply_dialect_adjustments


def _apply_dialect_adjustments_safe(self, sql: str, dialect: str):
    """Apply date rewrites without destructive parenthesis/string replacement."""
    if dialect == "oracle":
        adjusted = sql.replace("CURRENT_DATE", "TRUNC(SYSDATE)")
        adjusted = re.sub(
            r"DATE_SUB\(TRUNC\(SYSDATE\),\s*(\d+)\)",
            r"TRUNC(SYSDATE) - \1",
            adjusted,
        )
        return adjusted

    if dialect == "tsql":
        adjusted = sql.replace("CURRENT_DATE", "CAST(GETDATE() AS DATE)")
        adjusted = re.sub(
            r"DATE_SUB\(CAST\(GETDATE\(\) AS DATE\),\s*(\d+)\)",
            r"DATEADD(DAY, -\1, CAST(GETDATE() AS DATE))",
            adjusted,
        )
        return adjusted

    if dialect == "postgres":
        return re.sub(
            r"DATE_SUB\(CURRENT_DATE,\s*(\d+)\)",
            r"CURRENT_DATE - INTERVAL '\1 days'",
            sql,
        )

    return _original_apply_dialect_adjustments(self, sql, dialect)


NL2SQLGenerator._apply_dialect_adjustments = _apply_dialect_adjustments_safe


_original_generate = NL2SQLGenerator.generate


def _generate_normalized(self, text: str, dialect: str = None, table_hint: str = None, column_hints=None):
    """Normalize direct-call inputs so core and API callers share dialect semantics."""
    normalized_dialect = (dialect or self.default_dialect).strip().lower()
    if normalized_dialect not in SUPPORTED_DIALECTS:
        raise ValueError(
            f"Unsupported dialect: {dialect}. Supported: {', '.join(SUPPORTED_DIALECTS)}"
        )
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _original_generate(
        self,
        text,
        normalized_dialect,
        table_hint.strip() if isinstance(table_hint, str) else table_hint,
        column_hints,
    )


NL2SQLGenerator.generate = _generate_normalized
