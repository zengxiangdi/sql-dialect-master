"""Regression tests for NL2SQL template regex hardening."""

from backend.core.nl2sql_components.templates import (
    DEFAULT_QUERY_TEMPLATES,
    _TEMPLATE_CAPTURE_LIMIT,
)


def _templates_by_name():
    return {template.name: template for template in DEFAULT_QUERY_TEMPLATES}


def test_multi_segment_templates_use_bounded_captures():
    templates = _templates_by_name()
    hardened = (
        "top_n_query",
        "count_by_group",
        "aggregate_query",
        "condition_query",
        "join_query",
        "select_with_columns",
    )

    for name in hardened:
        pattern = templates[name].pattern
        assert f"{{1,{_TEMPLATE_CAPTURE_LIMIT}}}" in pattern
        assert ".+?" not in pattern


def test_hardened_templates_still_match_representative_queries():
    templates = _templates_by_name()
    cases = {
        "top_n_query": "查询前10个客户 按销售额 排序",
        "count_by_group": "统计每个部门的数量",
        "aggregate_query": "计算订单的平均金额",
        "condition_query": "查询年龄大于18的用户",
        "join_query": "查询用户和订单的数据",
        "select_with_columns": "查询姓名 年龄 用户表",
    }

    for name, text in cases.items():
        assert templates[name].match(text) is not None, name


def test_hardened_templates_bound_long_adversarial_input():
    templates = _templates_by_name()
    adversarial = "x" * (_TEMPLATE_CAPTURE_LIMIT * 4)

    for name in (
        "top_n_query",
        "count_by_group",
        "aggregate_query",
        "condition_query",
        "join_query",
        "select_with_columns",
    ):
        # The match is intentionally exercised with input much larger than
        # any individual capture so the regex cannot backtrack over an
        # unbounded wildcard segment.
        templates[name].match(adversarial)
