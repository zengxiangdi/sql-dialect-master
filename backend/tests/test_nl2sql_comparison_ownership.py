"""Regression tests for C4: inclusive comparison semantics in _extract_conditions_enhanced.

These tests verify that the canonical nl2sql_legacy implementation correctly
handles >= and <= without reduction to > or <.
"""
import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator


def _where_expression(text: str) -> exp.Expression:
    result = NL2SQLGenerator().generate(text, "postgres")
    assert result.success
    tree = sqlglot.parse_one(result.sql, read="postgres")
    where = tree.find(exp.Where)
    assert where is not None
    return where.this


def test_gte_not_reduced_to_gt():
    where = _where_expression("find products with price greater than or equal to 10")
    gte_nodes = list(where.find_all(exp.GTE))
    gt_nodes = list(where.find_all(exp.GT))
    assert len(gte_nodes) == 1
    assert len(gt_nodes) == 0


def test_lte_not_reduced_to_lt():
    where = _where_expression("find products with price less than or equal to 10")
    lte_nodes = list(where.find_all(exp.LTE))
    lt_nodes = list(where.find_all(exp.LT))
    assert len(lte_nodes) == 1
    assert len(lt_nodes) == 0


def test_gt_still_works():
    where = _where_expression("find products with price greater than 10")
    gt_nodes = list(where.find_all(exp.GT))
    gte_nodes = list(where.find_all(exp.GTE))
    assert len(gt_nodes) == 1
    assert len(gte_nodes) == 0


def test_lt_still_works():
    where = _where_expression("find products with price less than 10")
    lt_nodes = list(where.find_all(exp.LT))
    lte_nodes = list(where.find_all(exp.LTE))
    assert len(lt_nodes) == 1
    assert len(lte_nodes) == 0


def test_chinese_gte():
    where = _where_expression("查询价格大于等于100的产品")
    gte_nodes = list(where.find_all(exp.GTE))
    gt_nodes = list(where.find_all(exp.GT))
    assert len(gte_nodes) == 1
    assert len(gt_nodes) == 0


def test_chinese_lte():
    where = _where_expression("查询价格小于等于100的产品")
    lte_nodes = list(where.find_all(exp.LTE))
    lt_nodes = list(where.find_all(exp.LT))
    assert len(lte_nodes) == 1
    assert len(lt_nodes) == 0
