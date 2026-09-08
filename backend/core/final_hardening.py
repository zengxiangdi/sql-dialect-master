"""Final compatibility hardening patches for legacy helper implementations."""

import re

from sqlglot import exp

from .nl2sql import NL2SQLGenerator
from .parser import SQLParser
from .post_processor import PostProcessor


# Parser: normalize direct-call dialects the same way as the API boundary.
_original_parser_init = SQLParser.__init__


def _parser_init_normalized(self, dialect: str = "hive"):
    return _original_parser_init(self, dialect.strip().lower())


SQLParser.__init__ = _parser_init_normalized


# Parser: aggregation is not limited to GROUP BY; aggregate functions also count.
_original_has_aggregation = SQLParser._has_aggregation


def _has_aggregation_complete(self, ast):
    return (
        _original_has_aggregation(self, ast)
        or ast.find(exp.AggFunc) is not None
    )


SQLParser._has_aggregation = _has_aggregation_complete


# Post processor: Oracle DECODE treats NULL = NULL as a match. Convert the
# generated equality into IS NULL for NULL search values.
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


# Post processor: GROUP_CONCAT(expr) uses comma as MySQL's default separator.
# The legacy rule emits an empty separator because its optional capture group is
# unmatched, so repair that exact generated form before returning the result.
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


# NL2SQL: English inclusive comparison phrases must not degrade to strict
# comparisons in the legacy condition extractor.
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
