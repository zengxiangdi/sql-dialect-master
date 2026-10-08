#!/usr/bin/env python3
"""P8 NL2SQL pipeline: suggestion generation (moved from nl2sql_legacy).

``generate_suggestions`` is a verbatim move of
``nl2sql_legacy._generate_suggestions``.
"""


def generate_suggestions(text: str, sql: str, dialect: str) -> list:
    """Generate improvement suggestions."""
    suggestions = []
    if "table_name" in sql:
        suggestions.append("💡 请指定具体的表名，如：用户表、订单表")
    if "column >" in sql or "column <" in sql or "column =" in sql:
        suggestions.append("💡 请指定具体的列名用于条件判断，如：年龄大于30")
    if dialect == "hive" and "SELECT *" in sql:
        suggestions.append("💡 Hive 建议指定具体列名以提高性能")
    if "JOIN" not in sql and any(k in text for k in ["关联", "连接", "join", "和", "与"]):
        suggestions.append("💡 检测到关联需求，请明确指定两个表名")
    if "?" in sql:
        suggestions.append("💡 请替换 ? 占位符为实际值")
    if "GROUP BY" in sql and "HAVING" not in sql:
        suggestions.append("💡 可以添加 HAVING 子句过滤分组结果")
    if dialect == "hive" and "ORDER BY" in sql and "LIMIT" not in sql:
        suggestions.append("💡 Hive 中 ORDER BY 建议配合 LIMIT 使用")
    if "DELETE" in sql and "WHERE" not in sql:
        suggestions.append("⚠️ DELETE 没有 WHERE 条件将删除所有数据！")
    if "UPDATE" in sql and "WHERE" not in sql:
        suggestions.append("⚠️ UPDATE 没有 WHERE 条件将更新所有数据！")
    return suggestions
