#!/usr/bin/env python3
"""SQL templates and examples for SQL Dialect Master UI.

Centralizes all SQL templates, examples, and category definitions.
"""
from typing import Dict

# =============================================================================
# SQL Templates for Quick Start
# =============================================================================

TEMPLATES: Dict[str, str] = {
    "-- Select a template --": "",
    # Basic queries
    "📅 Last 7 days data": "SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)",
    "🔝 Top 100 with LIMIT": "SELECT * FROM users ORDER BY score DESC LIMIT 100",
    "🎲 DISTINCT with ORDER": "SELECT DISTINCT category, brand FROM products ORDER BY category, brand",
    "🔄 COALESCE null handling": "SELECT id, COALESCE(nickname, username, email, 'Anonymous') AS display_name FROM users",
    # Window functions
    "📊 Window ROW_NUMBER": "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees",
    "📊 Window LAG/LEAD": "SELECT date, amount, LAG(amount, 1, 0) OVER (ORDER BY date) AS prev_amount, LEAD(amount, 1, 0) OVER (ORDER BY date) AS next_amount FROM sales",
    "📊 Window RANK/DENSE_RANK": "SELECT name, score, RANK() OVER (ORDER BY score DESC) AS rank, DENSE_RANK() OVER (ORDER BY score DESC) AS dense_rank FROM students",
    "📊 Window NTILE": "SELECT name, salary, NTILE(4) OVER (ORDER BY salary DESC) AS quartile FROM employees",
    "📊 Window Running Total": "SELECT date, amount, SUM(amount) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING) AS running_total FROM sales",
    # JSON operations
    "🔗 JSON nested parse": "SELECT id, GET_JSON_OBJECT(data, '$.items[0].name') AS first_item FROM events",
    "🔗 JSON array extract": "SELECT id, JSON_EXTRACT(metadata, '$.tags') AS tags FROM products",
    "🔗 JSON object build": "SELECT id, JSON_OBJECT('name', name, 'email', email) AS user_json FROM users",
    # Array operations
    "📦 Array explode": "SELECT id, tag FROM products LATERAL VIEW EXPLODE(tags) t AS tag",
    "📦 Array aggregate": "SELECT user_id, COLLECT_LIST(product_id) AS purchased_products FROM orders GROUP BY user_id",
    "📦 Array contains": "SELECT * FROM products WHERE ARRAY_CONTAINS(tags, 'sale')",
    # Aggregations
    "📈 Group aggregation": "SELECT dept, COUNT(*) AS cnt, AVG(salary) AS avg_sal FROM employees GROUP BY dept",
    "📈 HAVING filter": "SELECT dept, COUNT(*) AS emp_count FROM employees GROUP BY dept HAVING COUNT(*) > 5 ORDER BY emp_count DESC",
    "🔄 String aggregation": "SELECT dept, COLLECT_LIST(name) AS names FROM employees GROUP BY dept",
    "📈 Multiple aggregates": "SELECT category, COUNT(*) AS cnt, SUM(price) AS total, AVG(price) AS avg_price, MAX(price) AS max_price FROM products GROUP BY category",
    # Joins
    "🔗 Multi-table JOIN": "SELECT u.name, o.order_id, p.product_name FROM users u JOIN orders o ON u.id = o.user_id JOIN products p ON o.product_id = p.id",
    "🔗 LEFT JOIN with NULL": "SELECT u.name, COUNT(o.id) AS order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.name",
    "🔗 Self JOIN": "SELECT e.name AS employee, m.name AS manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.id",
    "🔗 CROSS JOIN": "SELECT p.name, c.color FROM products p CROSS JOIN colors c",
    # Subqueries
    "📉 Subquery IN clause": "SELECT * FROM products WHERE category_id IN (SELECT id FROM categories WHERE status = 'active')",
    "📉 Correlated subquery": "SELECT * FROM employees e WHERE salary > (SELECT AVG(salary) FROM employees WHERE dept = e.dept)",
    "📉 EXISTS subquery": "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.amount > 1000)",
    # CTEs
    "🔀 CTE basic": "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users WHERE created_at > '2024-01-01'",
    "🔀 CTE recursive": "WITH RECURSIVE cte AS (SELECT 1 AS n UNION ALL SELECT n+1 FROM cte WHERE n < 10) SELECT * FROM cte",
    "🔀 CTE multiple": "WITH sales_2024 AS (SELECT * FROM sales WHERE YEAR(date) = 2024), top_products AS (SELECT product_id, SUM(amount) AS total FROM sales_2024 GROUP BY product_id) SELECT * FROM top_products ORDER BY total DESC LIMIT 10",
    # Date operations
    "📅 Date extraction": "SELECT YEAR(created_at) AS year, MONTH(created_at) AS month, COUNT(*) AS cnt FROM orders GROUP BY YEAR(created_at), MONTH(created_at)",
    "📅 Date range filter": "SELECT * FROM logs WHERE log_time BETWEEN '2024-01-01' AND '2024-12-31'",
    "📅 Date arithmetic": "SELECT id, created_at, DATE_ADD(created_at, 30) AS expires_at FROM subscriptions",
    "📅 Date formatting": "SELECT id, DATE_FORMAT(created_at, '%Y-%m-%d') AS formatted_date FROM orders",
    # CASE expressions
    "🎯 CASE WHEN": "SELECT id, name, CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' WHEN score >= 60 THEN 'C' ELSE 'F' END AS grade FROM students",
    "🎯 CASE with aggregation": "SELECT SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending FROM orders",
    # Set operations
    "🔢 UNION ALL": "SELECT 'Q1' AS quarter, SUM(amount) AS total FROM sales WHERE month <= 3 UNION ALL SELECT 'Q2', SUM(amount) FROM sales WHERE month BETWEEN 4 AND 6",
    "🔢 INTERSECT": "SELECT user_id FROM orders WHERE YEAR(created_at) = 2023 INTERSECT SELECT user_id FROM orders WHERE YEAR(created_at) = 2024",
    "🔢 EXCEPT": "SELECT user_id FROM users EXCEPT SELECT DISTINCT user_id FROM orders",
    # Advanced
    "🚀 Pivot simulation": "SELECT product_id, SUM(CASE WHEN month = 1 THEN amount END) AS jan, SUM(CASE WHEN month = 2 THEN amount END) AS feb, SUM(CASE WHEN month = 3 THEN amount END) AS mar FROM sales GROUP BY product_id",
    "🚀 Percentile": "SELECT dept, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary) AS median_salary FROM employees GROUP BY dept",
    "🚀 Cumulative distribution": "SELECT name, salary, CUME_DIST() OVER (ORDER BY salary) AS percentile FROM employees"
}

# =============================================================================
# Category Emoji Mapping
# =============================================================================

CATEGORY_EMOJI: Dict[str, str] = {
    "string": "📝 String",
    "date": "📅 Date/Time",
    "math": "🔢 Math",
    "aggregate": "📊 Aggregate",
    "window": "🪟 Window",
    "conditional": "❓ Conditional",
    "conversion": "🔄 Conversion",
    "json": "📋 JSON",
    "array": "📦 Array",
    "system": "⚙️ System",
    "geo": "🌍 Geospatial"
}

# =============================================================================
# NL2SQL Examples
# =============================================================================

NL_EXAMPLES: Dict[str, str] = {
    "-- 选择示例 / Select Example --": "",
    "📊 统计类 / Aggregation": "统计所有用户的数量",
    "📅 时间筛选 / Date Filter": "查询最近7天的订单",
    "💰 条件筛选 / Condition": "查询金额大于100的订单",
    "👥 分组统计 / Group By": "按部门分组统计员工数量",
    "🔝 排序限制 / Order & Limit": "查询前10个用户按得分降序排列",
    "🔗 关联查询 / Join": "查询用户和订单关联的数据",
    "📈 平均值 / Average": "查询员工的平均薪资",
    "🔍 模糊搜索 / Like": "查询名字包含'张'的用户",
    "📆 本月数据 / This Month": "查询本月所有订单的总金额",
    "🏆 Top N / Ranking": "查询销售额最高的前5个产品",
}

# =============================================================================
# Type Categories for Type Mapping UI
# =============================================================================

TYPE_CATEGORIES: Dict[str, list] = {
    "String Types": ["STRING", "VARCHAR", "CHAR", "TEXT", "MEDIUMTEXT", "LONGTEXT"],
    "Numeric Types": ["BIGINT", "INT", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "MONEY", "SERIAL"],
    "Boolean & Bit": ["BOOLEAN", "BIT"],
    "Date/Time Types": ["DATE", "TIME", "TIMESTAMP", "TIMESTAMP_TZ", "INTERVAL", "YEAR"],
    "Complex Types": ["ARRAY", "MAP", "STRUCT", "JSON", "JSONB", "XML"],
    "Binary Types": ["BINARY"],
    "Special Types": ["UUID", "INET", "GEOMETRY", "GEOGRAPHY", "ENUM", "SET"]
}
