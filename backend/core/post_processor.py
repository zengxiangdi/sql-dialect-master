#!/usr/bin/env python3
"""Post-processor for dialect-specific SQL transformations.

Uses the rule engine for declarative transformations and handles
complex cases that require custom logic.
"""
import logging
from typing import Tuple, List, Callable

import sqlglot
from sqlglot import exp

from .rules import rule_engine, RuleEngine, DYNAMIC_SEPARATOR_FAIL_NOTE
from .function_call_scanner import replace_function_calls
from .p1_sql_scanner import mask_non_executable

logger = logging.getLogger(__name__)


class PostProcessor:
    """Apply dialect-specific fixes after sqlglot transpilation."""

    def __init__(self, engine: RuleEngine = None):
        self.engine = engine or rule_engine

    def process(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        result = sql
        all_notes = []
        result, rule_notes = self.engine.apply_rules(result, source, target)
        all_notes.extend(rule_notes)
        result, custom_notes = self._apply_custom_transformations(result, source, target)
        all_notes.extend(custom_notes)
        warnings = self._check_warnings(sql, source, target)
        all_notes.extend(warnings)
        return result, all_notes

    def _apply_custom_transformations(self, sql: str, source: str, target: str) -> Tuple[str, List[str]]:
        result = sql
        notes = []
        if source == "oracle" and target in ("hive", "spark", "databricks"):
            result, listagg_notes = self._convert_listagg_to_array_join(result)
            notes.extend(listagg_notes)
        return result, notes

    def _replace_function_calls(self, sql: str, function_name: str, replacer: Callable[[str, str], str]) -> str:
        """Replace function calls using the shared quote/comment-aware scanner."""
        return replace_function_calls(sql, function_name, replacer)

    def _check_warnings(self, sql: str, source: str, target: str) -> List[str]:
        warnings = []
        sql_upper = mask_non_executable(sql).upper()
        if source == "hive" and "INSERT OVERWRITE" in sql_upper and target in ("mysql", "postgres", "tsql", "oracle"):
            warnings.append(f"WARNING: INSERT OVERWRITE not supported in {target}. Use TRUNCATE + INSERT or MERGE instead.")
        if source == "oracle" and "CONNECT BY" in sql_upper and target in ("hive", "postgres", "mysql"):
            warnings.append("WARNING: CONNECT BY requires manual conversion to WITH RECURSIVE CTE")
        if source == "hive" and target in ("mysql", "postgres", "oracle", "tsql") and ("DISTRIBUTE BY" in sql_upper or "CLUSTER BY" in sql_upper):
            warnings.append("WARNING: DISTRIBUTE BY/CLUSTER BY are Hive-specific hints, removed in target")
        if any(kw in sql_upper for kw in ["CREATE PROCEDURE", "CREATE FUNCTION", "BEGIN", "DECLARE"]):
            warnings.append("WARNING: Procedural code detected. Stored procedure syntax varies significantly between databases.")
        if "MATERIALIZED VIEW" in sql_upper:
            warnings.append("WARNING: Materialized view syntax and refresh mechanisms vary by database.")
        return warnings

    def _convert_listagg_to_array_join(self, sql: str) -> Tuple[str, List[str]]:
        """Convert Oracle LISTAGG→Hive-family aggregated output to ARRAY_JOIN(COLLECT_LIST(...)).

        sqlglot transpiles Oracle LISTAGG to GROUP_CONCAT for hive/spark/databricks,
        but Hive does not natively support GROUP_CONCAT. This method rewrites the
        sqlglot-produced GROUP_CONCAT(... ORDER BY ..., sep) form to
        ARRAY_JOIN(COLLECT_LIST(expr), sep). Ordering semantics are explicitly
        noted as lost because Hive's COLLECT_LIST does not preserve input order.

        The separator is the last Ordered expression when it is a string Literal.
        """
        try:
            tree = sqlglot.parse_one(sql, read="hive")
        except sqlglot.errors.ParseError:
            return sql, []

        notes = []
        rewritten = False

        for node in list(tree.walk()):
            if not isinstance(node, exp.GroupConcat):
                continue
            expr = node.this
            sep = node.args.get("separator")

            has_order = isinstance(expr, exp.Order)
            if has_order:
                inner_expr = expr.this
                # The separator is encoded as the last Ordered expression when it's a string literal
                order_exprs = expr.expressions
                if (
                    order_exprs
                    and isinstance(order_exprs[-1].this, exp.Literal)
                    and order_exprs[-1].this.is_string
                ):
                    sep = order_exprs[-1].this
            else:
                inner_expr = expr

            collect_list = exp.Anonymous(
                this="COLLECT_LIST",
                expressions=[inner_expr],
            )
            array_join = exp.Anonymous(
                this="ARRAY_JOIN",
                expressions=[collect_list, sep or exp.Literal.string(",")],
            )
            node.replace(array_join)
            if has_order:
                notes.append(
                    "LISTAGG ordering semantics cannot be preserved in Hive; "
                    "converted to ARRAY_JOIN(COLLECT_LIST()) which does not guarantee order"
                )
            rewritten = True

        if rewritten:
            return tree.sql(dialect="hive"), notes
        return sql, notes

    def get_stats(self) -> dict:
        return {
            "rule_engine": self.engine.get_stats(),
            "custom_handlers": [
                "LISTAGG to ARRAY_JOIN (Hive)",
            ],
        }
